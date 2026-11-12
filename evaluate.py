"""Runs the classifier over cases.yaml and writes RESULTS.md and results.json.

    python3 run.py eval              all the cases, one model call each
    python3 run.py eval --limit 5    a smoke test: the first 5 cases, printed, nothing written
    python3 run.py eval --fresh      forget the answers of a run that was cut short

Two rules the script keeps:
  - A provider failure is not a verdict. If the model stops answering (a daily limit, a wrong
    key, an outage) the run stops and nothing is scored. The answers so far are kept, and the
    same command carries on from there.
  - Every number is printed with its count, because 52 cases is a small sample.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

import classifier

ROOT = Path(__file__).resolve().parent
RESULTS_MD = ROOT / "RESULTS.md"
RESULTS_JSON = ROOT / "results.json"
PROGRESS = ROOT / ".eval_progress.json"  # answers of a run that has not finished
TOLD = ("Q1", "Q2", "Q3", "Q4", "Q5")  # the open questions the classifier is told about


def load_cases() -> list[dict[str, Any]]:
    """The cases, with each context name replaced by the context itself."""
    data = yaml.safe_load((ROOT / "cases.yaml").read_text(encoding="utf-8"))
    cases = []
    for case in data["cases"]:
        name = case.get("context")
        cases.append({**case, "context_name": name, "context": data["contexts"][name] if name else None})
    return cases


def wilson(k: int, n: int) -> tuple[float, float]:
    """95 percent interval for k right out of n. It behaves on small samples and near 0 and 100 percent."""
    if n == 0:
        return 0.0, 0.0
    z, p = 1.96, k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def share(k: int, n: int) -> str:
    if n == 0:
        return "none"
    low, high = wilson(k, n)
    return f"{100 * k / n:.0f}% ({k} of {n}, 95% interval {100 * low:.0f} to {100 * high:.0f})"


def summarize(cases: list[dict[str, Any]], predictions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Every figure in the report, from the labels and the classifier's answers."""
    rows = []
    for case in cases:
        answer = predictions[case["id"]]
        rows.append({
            "id": case["id"], "kind": case["kind"], "gold": case["gold"], "predicted": answer["verdict"],
            "right": answer["verdict"] == case["gold"], "action": answer["action"],
            "set": case.get("set"), "open_question": case.get("open_question"),
            "analysis": answer["analysis"], "question": answer["question"], "why": case["why"],
            "error": answer.get("error"),
        })

    def count(selected: list[dict[str, Any]]) -> dict[str, int]:
        return {"right": sum(row["right"] for row in selected), "n": len(selected)}

    violations = [row for row in rows if row["gold"] == "violation"]
    allowed = [row for row in rows if row["gold"] == "allow"]
    gaps = [row for row in rows if row["gold"] == "undecided"]
    sets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["set"]:
            sets.setdefault(row["set"], []).append(row)
    latencies = [p["latency_ms"] for p in predictions.values() if p.get("latency_ms")]
    return {
        "overall": count(rows),
        "by_kind": {kind: count([row for row in rows if row["kind"] == kind]) for kind in classifier.KINDS},
        "confusion": {gold: {said: sum(1 for row in rows if row["gold"] == gold and row["predicted"] == said)
                             for said in classifier.VERDICTS} for gold in classifier.VERDICTS},
        # What matters on the request path is the action, after the table for undecided events.
        "violations_let_through": {"k": sum(row["action"] == "allow" for row in violations), "n": len(violations)},
        "allowed_but_blocked": {"k": sum(row["action"] == "block" for row in allowed), "n": len(allowed)},
        "gaps": {
            "all": count(gaps),
            "told": count([row for row in gaps if row["open_question"] in TOLD]),
            "not_told": count([row for row in gaps if row["open_question"] in ("Q6", "Q7")]),
            "missing_context": count([row for row in gaps if row["open_question"] == "missing context"]),
        },
        "sets": {name: {"cases": [row["id"] for row in members], "all_right": all(row["right"] for row in members)}
                 for name, members in sets.items()},
        "no_verdict": sum(1 for row in rows if row["error"]),
        # A reply that could not be read is handled as undecided. Where my label is also undecided,
        # that counts as right although the model judged nothing, so it is reported separately.
        "no_verdict_counted_right": sum(1 for row in rows if row["error"] and row["right"]),
        "median_latency_ms": round(statistics.median(latencies)) if latencies else None,
        "mean_input_tokens": round(statistics.mean(p["input_tokens"] for p in predictions.values())),
        "mean_output_tokens": round(statistics.mean(p["output_tokens"] for p in predictions.values())),
        "rows": rows,
    }


def _cell(text: Any) -> str:
    return " ".join(str(text or "").split()).replace("|", "/")


def report(run: dict[str, Any], s: dict[str, Any]) -> str:
    """RESULTS.md."""
    out: list[str] = []
    add = out.append
    add("# Results")
    add("")
    add("Generated by `python3 run.py eval`. Do not edit by hand: run it again.")
    add("")
    pace = f", paced at {run['calls_per_minute']:g} calls a minute" if run["calls_per_minute"] else ""
    add(f"- Model: `{run['model']}` through {run['provider']}{pace}")
    add(f"- Run finished: {run['finished_at']}")
    add(f"- Cases: {s['overall']['n']}, one model call each. Prompt fingerprint `{run['prompt_fingerprint']}`.")
    add("")
    add("## Headline")
    add("")
    add("| Measure | Result |")
    add("| --- | --- |")
    add(f"| Verdict matches my label | {share(s['overall']['right'], s['overall']['n'])} |")
    v, a = s["violations_let_through"], s["allowed_but_blocked"]
    add(f"| Violations that would get through (my label says violation, the guardrail allows) | {v['k']} of {v['n']} |")
    add(f"| Allowed events that would be blocked | {a['k']} of {a['n']} |")
    g = s["gaps"]
    add(f"| Undecided cases recognized as undecided | {g['all']['right']} of {g['all']['n']} |")
    add(f"| ... open questions the classifier is told about | {g['told']['right']} of {g['told']['n']} |")
    add(f"| ... open questions it is not told about | {g['not_told']['right']} of {g['not_told']['n']} |")
    add(f"| ... missing context | {g['missing_context']['right']} of {g['missing_context']['n']} |")
    add(f"| No verdict from the model (a reply that could not be read, scored as undecided) | {s['no_verdict']} |")
    if s["no_verdict"]:
        add(f"| ... of those, counted as right only because my label is also undecided | {s['no_verdict_counted_right']} |")
    add(f"| Median latency of the model call | {s['median_latency_ms']} ms |")
    add(f"| Tokens per call, on average | {s['mean_input_tokens']} in, {s['mean_output_tokens']} out |")
    add("")
    add("The intervals are wide because the sample is small. A difference smaller than the interval is noise.")
    add("")
    add("## By kind of event")
    add("")
    add("| Kind | Verdict matches my label |")
    add("| --- | --- |")
    for kind, c in s["by_kind"].items():
        add(f"| {kind} | {share(c['right'], c['n'])} |")
    add("")
    add("## Confusion matrix")
    add("")
    add("Rows are my labels. Columns are the classifier's verdicts.")
    add("")
    add("| | " + " | ".join(classifier.VERDICTS) + " |")
    add("| --- | " + " | ".join("---" for _ in classifier.VERDICTS) + " |")
    for gold in classifier.VERDICTS:
        add(f"| **{gold}** | " + " | ".join(str(s["confusion"][gold][said]) for said in classifier.VERDICTS) + " |")
    add("")
    add("## Same content, different position or context")
    add("")
    add("A set counts as right only if every case in it is right.")
    add("")
    add("| Set | Cases | All right |")
    add("| --- | --- | --- |")
    for name, members in s["sets"].items():
        add(f"| {name} | {', '.join(members['cases'])} | {'yes' if members['all_right'] else 'NO'} |")
    add("")
    wrong = [row for row in s["rows"] if not row["right"]]
    add(f"## Every case the classifier got wrong ({len(wrong)})")
    add("")
    if wrong:
        add("| Case | Kind | My label | Classifier | What the classifier said | Why my label |")
        add("| --- | --- | --- | --- | --- | --- |")
        for row in wrong:
            add(f"| {row['id']} | {row['kind']} | {row['gold']} | {row['predicted']} | {_cell(row['analysis'])} | {_cell(row['why'])} |")
    else:
        add("None.")
    add("")
    add("## All cases")
    add("")
    add("| Case | Kind | My label | Classifier | Guardrail action | |")
    add("| --- | --- | --- | --- | --- | --- |")
    for row in s["rows"]:
        add(f"| {row['id']} | {row['kind']} | {row['gold']} | {row['predicted']} | {row['action']} | {'' if row['right'] else 'different'} |")
    add("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the classifier on cases.yaml.")
    parser.add_argument("--limit", type=int, default=None, help="only the first N cases, as a smoke test")
    parser.add_argument("--fresh", action="store_true", help="forget the answers of a run that was cut short")
    args = parser.parse_args(argv)

    chosen = classifier.settings()
    if not chosen["configured"]:
        print("No model is configured. Copy .env.example to .env and add a key.", file=sys.stderr)
        return 2
    cases = load_cases()
    if args.limit:
        cases = cases[: args.limit]
    fingerprint = hashlib.sha256(classifier.build_system_prompt().encode("utf-8")).hexdigest()[:12]

    # Answers of a run that was cut short are reused only if the model and the prompt are the same.
    key = f"{chosen['model']}|{fingerprint}"
    answers: dict[str, dict[str, Any]] = {}
    if PROGRESS.exists() and not args.fresh and not args.limit:
        kept = json.loads(PROGRESS.read_text(encoding="utf-8"))
        if kept.get("key") == key:
            answers = kept["answers"]
    todo = [case for case in cases if case["id"] not in answers]
    print(f"Model: {chosen['model']} ({chosen['provider']}). Cases: {len(cases)}. Model calls to make: {len(todo)}.")
    if answers:
        print(f"Carrying on a run that was cut short: {len(answers)} answers are already saved (--fresh starts over).")
    if chosen["calls_per_minute"] and todo:
        minutes = math.ceil(len(todo) / chosen["calls_per_minute"])
        print(f"Paced at {chosen['calls_per_minute']:g} calls a minute (LLM_RPM): about {minutes} minute(s).")

    for case in todo:
        try:
            answer = classifier.classify(case["kind"], case["payload"], case["context"], fail_safe=False)
        except classifier.ModelError as error:
            print(f"\nStopped at {case['id']}: the model did not answer. Nothing was scored.", file=sys.stderr)
            if error.used_up:
                print("The provider's allowance for the day is used up. Run the same command after it resets", file=sys.stderr)
                print("(Gemini: midnight Pacific time) and it carries on from here.", file=sys.stderr)
            elif error.status in (400, 401, 403, 404):
                print("The provider rejected the request. Check the key and LLM_MODEL in .env.", file=sys.stderr)
            else:
                print("Try again in a few minutes: the same command carries on from here.", file=sys.stderr)
            print(f"The provider said: {str(error)[:400]}", file=sys.stderr)
            print(f"Saved so far: {len(answers)} of {len(cases)} answers.", file=sys.stderr)
            return 3
        answers[case["id"]] = answer
        if not args.limit:
            PROGRESS.write_text(json.dumps({"key": key, "answers": answers}, ensure_ascii=False), encoding="utf-8")
        same = "" if answer["verdict"] == case["gold"] else "   <-- different"
        print(f"  {case['id']:6} {case['kind']:14} my label: {case['gold']:10} classifier: {answer['verdict']:10}{same}")

    if args.limit:
        print("\nSmoke test only: nothing was written. Run without --limit for the report.")
        return 0

    summary = summarize(cases, answers)
    run = {
        "model": chosen["model"], "provider": chosen["provider"], "calls_per_minute": chosen["calls_per_minute"],
        "prompt_fingerprint": fingerprint,
        "finished_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    RESULTS_JSON.write_text(json.dumps({"run": run, "summary": summary}, indent=2, ensure_ascii=False), encoding="utf-8")
    RESULTS_MD.write_text(report(run, summary), encoding="utf-8")
    PROGRESS.unlink(missing_ok=True)

    overall, gaps = summary["overall"], summary["gaps"]["all"]
    print(f"\nVerdict matches my label: {share(overall['right'], overall['n'])}")
    print(f"Violations that would get through: {summary['violations_let_through']['k']} of {summary['violations_let_through']['n']}")
    print(f"Allowed events that would be blocked: {summary['allowed_but_blocked']['k']} of {summary['allowed_but_blocked']['n']}")
    print(f"Undecided cases recognized: {gaps['right']} of {gaps['n']}")
    print(f"\nReport: {RESULTS_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
