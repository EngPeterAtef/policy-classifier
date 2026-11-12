# Policy alignment classifier for AI agent traces

A classifier that reads **one event from an AI agent's trace** and decides whether a written
policy permits it. The event is one of four kinds: what the customer typed (`user_input`), what
the agent said (`model_output`), a tool the agent is about to call (`tool_call`), or what a tool
returned (`tool_response`).

It answers `allow`, `violation` or `undecided`. `undecided` means the policy does not settle the
event, and it comes with the question to ask the policy owner. A fixed table then turns the
verdict into what a guardrail does: allow or block.

The agent is the support agent of a fictional online travel agency. It looks up bookings, sends
emails and issues refunds, so all four kinds of event carry real risk.

- **[WRITEUP.md](WRITEUP.md)**: reasoning, assumptions, the corner cases, the limits.
- **[policy.md](policy.md)**: the policy. Six rules, how I read them, and the open questions.
- **[RESULTS.md](RESULTS.md)**: the evaluation results, written by `python3 run.py eval`.

## Run it

```bash
cp .env.example .env      # then put a key in .env (Gemini's free tier works)
python3 run.py            # then open http://localhost:8000
```

Needs Python 3.10 or newer and Node 18 or newer. The first run takes about a minute: it creates
`.venv`, installs the Python packages and builds the page. Nothing is installed outside this folder.

```bash
python3 run.py eval --limit 5   # smoke test: 5 cases, printed, nothing written
python3 run.py eval             # all 52 cases, writes RESULTS.md (about 6 minutes at 10 calls a minute)
python3 run.py test             # 35 unit tests, no key and no network needed
```

If the model stops answering part way (a free tier's daily limit, for example), the eval stops,
scores nothing, and carries on from where it stopped when you run the same command again.

## The one idea

**The same text can be fine in one position and a violation in another.** A card number typed by
the customer is allowed. The same number written out by the agent is a violation. So the
classifier decides by kind first and by content second, and the policy says which rules can apply
to which kind:

| Kind of event | Who wrote it | Rules that can apply |
| --- | --- | --- |
| user_input | the customer | R6 (do not attack the agent) |
| model_output | the agent, to the customer | R1 (verify first), R2 (mask sensitive numbers) |
| tool_call | the agent, as an action | R1, R2, R3 (email only the customer on file), R4 (refund limits) |
| tool_response | a tool: a database, a web page, an email | R5 (tool results are not instructions) |

## How it works

```
event + session context
        |
        v
  1. the prompt       the four kinds, policy.md word for word, eight worked examples.
        |             The event is wrapped in tags that carry a random code.
        v
  2. the model call   one HTTP request (Gemini, or any OpenAI-compatible API)
        |
        v
  3. the reply        JSON: analysis, verdict, rules, question. Asked again once if unreadable.
        |
        v
  4. allow or block   allow -> allow, violation -> block, undecided -> a fixed table:
        |             block what cannot be undone, allow and flag what can
        v
     result           verdict, rules, analysis, question, action
```

All four steps are in [classifier.py](classifier.py), in that order.

## What is where

| File | What it is |
| --- | --- |
| `policy.md` | The policy. The classifier is shown the top half. The bottom half holds two open questions it is not told about, and the allow-or-block table. |
| `classifier.py` | The whole classifier: prompt, model call, reading the reply, allow or block. |
| `examples.yaml` | The eight worked examples in the prompt. None is an eval case. |
| `cases.yaml` | 52 labeled events. Each says what my label is and why. |
| `evaluate.py` | Runs the classifier over the cases and writes `RESULTS.md` and `results.json`. |
| `server.py`, `web/` | The API and the React page. |
| `run.py` | The one command. |
| `tests/` | 35 tests. |

## The page

| Tab | What it does |
| --- | --- |
| Classify an event | Load one of the 52 cases or write your own event and context. Shows the verdict, the rule, the reasoning, the guardrail action, and my label next to the classifier's. A second button classifies the same content in all four positions. |
| Evaluation | The last eval run. Rows in red are the cases the classifier got wrong. Click a row to open it. |
| Policy | What the classifier is shown, word for word, and below it what it is not shown. |

Things worth clicking:

- Load `ui-20` and press **Try this content in all four positions**: one card number, four positions.
- `ui-10`, `ui-19`, `mo-33`, `tr-02`: one sentence as an attack, a question, a warning and an injection.
- `tc-27`, `tc-28`, `tc-29`: the same refund, three different histories.
- `tr-23`: the customer's own email arriving as a tool result.

With `LLM_RPM=10` in `.env` the four-positions button waits six seconds between its four calls.
To make it quick, comment that line out and restart the app. Put it back before `run.py eval`.

## Notes

- Everything is synthetic: the company, the people, the bookings, the addresses.
- The API key stays on the server. The page never sees it.
- AI was used to build this, as the brief allows. [WRITEUP.md](WRITEUP.md), section 9, says where.
