import { useEffect, useMemo, useState } from "react";

// The whole page: three tabs over five API routes (see server.py).

const KINDS = ["user_input", "model_output", "tool_call", "tool_response"];
const KIND_HELP = {
  user_input: "What the customer typed.",
  model_output: "What the agent said to the customer.",
  tool_call: "A tool the agent is about to call, with its arguments.",
  tool_response: "What a tool returned to the agent.",
};
const STARTER = {
  user_input: { text: "Hi, what is the checked baggage allowance on Zephyr Air economy?" },
  model_output: { text: "Your flight ZP 204 from Cairo to Dubai departs on 12 March at 09:40." },
  tool_call: { tool: "send_email", arguments: { to: "amira.hassan@mail.example", subject: "Your e-ticket", body: "Hello Amira, your e-ticket is attached." } },
  tool_response: { tool: "web_fetch", result: "Dunestay Marina Hotel. Check-in from 15:00, check-out by 12:00." },
};

async function api(path, body) {
  const options = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : undefined;
  let response;
  try {
    response = await fetch(path, options);
  } catch (error) {
    throw new Error("Cannot reach the server. Is `python3 run.py` still running?");
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const data = await response.json();
      if (data && data.detail) detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch (ignored) {
      // keep the status line
    }
    throw new Error(detail);
  }
  return response.json();
}

const pretty = (value) => JSON.stringify(value, null, 2);

// One line that says what an event is, for the case picker.
function preview(kind, payload) {
  let text;
  if (kind === "user_input" || kind === "model_output") text = payload.text ?? "";
  else if (kind === "tool_call") text = `${payload.tool}(...)`;
  else text = `${payload.tool} returned ${typeof payload.result === "string" ? payload.result : "a record"}`;
  text = String(text).replace(/\s+/g, " ");
  return text.length > 70 ? `${text.slice(0, 69)}...` : text;
}

// The text a person would call "the content" of an event, for the four-positions test.
function mainText(kind, payload) {
  if (kind === "user_input" || kind === "model_output") return payload.text ?? "";
  if (kind === "tool_call") {
    const strings = Object.values(payload.arguments ?? {}).filter((value) => typeof value === "string");
    return strings.sort((a, b) => b.length - a.length)[0] ?? "";
  }
  return typeof payload.result === "string" ? payload.result : pretty(payload.result);
}

function Badge({ verdict }) {
  return <span className={`badge badge-${verdict}`}>{verdict}</span>;
}

function Result({ title, result, gold }) {
  return (
    <div className="card">
      {title && <div className="label">{title}</div>}
      <div className="verdict-line">
        <Badge verdict={result.verdict} />
        {result.rules.length > 0 && <span className="mono">{result.rules.join(", ")}</span>}
        <span className={`action action-${result.action}`}>
          guardrail: {result.action}
          {result.review ? " and flag for a human" : ""}
        </span>
      </div>
      <p>{result.analysis}</p>
      {result.question && (
        <p>
          <b>Question for the policy owner:</b> {result.question}
        </p>
      )}
      <p className="muted small">{result.action_reason}</p>
      {gold && (
        <p className={result.verdict === gold.gold ? "agree" : "disagree"}>
          My label: <Badge verdict={gold.gold} /> {result.verdict === gold.gold ? "The classifier agrees." : "The classifier disagrees."}
          <br />
          <span className="small">{gold.why}</span>
        </p>
      )}
      <p className="muted small">
        {result.model}
        {result.latency_ms != null && `, ${result.latency_ms} ms, ${result.input_tokens} tokens in, ${result.output_tokens} out`}
      </p>
    </div>
  );
}

function TryIt({ cases, openId }) {
  const [caseId, setCaseId] = useState("");
  const [kind, setKind] = useState("user_input");
  const [payloadText, setPayloadText] = useState(pretty(STARTER.user_input));
  const [contextText, setContextText] = useState(pretty({ channel: "chat", verified: false }));
  const [results, setResults] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const byId = useMemo(() => Object.fromEntries(cases.map((item) => [item.id, item])), [cases]);

  function load(id) {
    setCaseId(id);
    setResults([]);
    setError("");
    const item = byId[id];
    if (!item) return;
    setKind(item.kind);
    setPayloadText(pretty(item.payload));
    setContextText(item.context ? pretty(item.context) : "");
  }

  // The Results tab can ask this tab to open a case.
  useEffect(() => {
    if (openId && byId[openId]) load(openId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openId, byId]);

  function changeKind(next) {
    setKind(next);
    setCaseId("");
    setResults([]);
    setPayloadText(pretty(STARTER[next]));
  }

  function readForm() {
    let payload;
    let context = null;
    try {
      payload = JSON.parse(payloadText);
    } catch (problem) {
      throw new Error(`The payload is not valid JSON: ${problem.message}`);
    }
    if (contextText.trim()) {
      try {
        context = JSON.parse(contextText);
      } catch (problem) {
        throw new Error(`The context is not valid JSON: ${problem.message}`);
      }
    }
    return { payload, context };
  }

  async function run(events) {
    setBusy(true);
    setError("");
    setResults([]);
    try {
      const answers = await Promise.all(events.map((event) => api("/api/classify", { kind: event.kind, payload: event.payload, context: event.context })));
      setResults(answers.map((result, index) => ({ result, title: events[index].title, gold: events[index].gold })));
    } catch (problem) {
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  }

  function classifyOne() {
    try {
      const { payload, context } = readForm();
      run([{ kind, payload, context, title: "", gold: byId[caseId] }]);
    } catch (problem) {
      setError(problem.message);
    }
  }

  // The same content as a customer message, an agent message, a tool call and a tool result.
  function classifyFour() {
    try {
      const { payload, context } = readForm();
      const content = mainText(kind, payload);
      const ref = context?.booking?.ref ?? "SKF-7F3K9Q";
      run([
        { kind: "user_input", payload: { text: content }, context, title: "user_input: the customer typed it" },
        { kind: "model_output", payload: { text: content }, context, title: "model_output: the agent said it" },
        { kind: "tool_call", payload: { tool: "add_note", arguments: { booking_ref: ref, note: content } }, context, title: "tool_call: the agent wrote it into a note" },
        { kind: "tool_response", payload: { tool: "web_fetch", result: content }, context, title: "tool_response: a web page returned it" },
      ]);
    } catch (problem) {
      setError(problem.message);
    }
  }

  return (
    <div className="columns">
      <div className="card">
        <label className="field">
          <span className="label">Load one of the {cases.length} labeled cases</span>
          <select value={caseId} onChange={(event) => load(event.target.value)}>
            <option value="">(write your own below)</option>
            {KINDS.map((group) => (
              <optgroup key={group} label={group}>
                {cases.filter((item) => item.kind === group).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.id} [{item.gold}] {preview(item.kind, item.payload)}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="label">Kind of event</span>
          <select value={kind} onChange={(event) => changeKind(event.target.value)}>
            {KINDS.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <span className="muted small">{KIND_HELP[kind]}</span>
        </label>
        <label className="field">
          <span className="label">Payload (JSON)</span>
          <textarea rows={9} dir="auto" value={payloadText} onChange={(event) => setPayloadText(event.target.value)} />
        </label>
        <label className="field">
          <span className="label">Session context (JSON, or empty for none)</span>
          <textarea rows={7} value={contextText} onChange={(event) => setContextText(event.target.value)} />
        </label>
        <div className="buttons">
          <button className="primary" disabled={busy} onClick={classifyOne}>
            {busy ? "Classifying..." : "Classify"}
          </button>
          <button disabled={busy} onClick={classifyFour}>
            Try this content in all four positions
          </button>
        </div>
        {error && <p className="error">{error}</p>}
      </div>
      <div>
        {results.length === 0 && !busy && (
          <div className="card muted">
            The verdict appears here. The classifier answers allow, violation or undecided. A fixed table then turns
            that into what the guardrail does: allow or block.
          </div>
        )}
        {results.map((item, index) => (
          <Result key={index} title={item.title} result={item.result} gold={item.gold} />
        ))}
      </div>
    </div>
  );
}

function Results({ results, open }) {
  if (!results) {
    return (
      <div className="card">
        No results yet. Run <code>python3 run.py eval</code> in a terminal, then reload this page.
      </div>
    );
  }
  const { run, summary } = results;
  const share = (count) => `${count.right} of ${count.n}`;
  return (
    <div>
      <div className="card">
        <p className="muted small">
          {run.model} through {run.provider}, finished {run.finished_at}. Prompt fingerprint {run.prompt_fingerprint}.
        </p>
        <table>
          <tbody>
            <tr><td>Verdict matches my label</td><td><b>{share(summary.overall)}</b></td></tr>
            <tr><td>Violations that would get through</td><td>{summary.violations_let_through.k} of {summary.violations_let_through.n}</td></tr>
            <tr><td>Allowed events that would be blocked</td><td>{summary.allowed_but_blocked.k} of {summary.allowed_but_blocked.n}</td></tr>
            <tr><td>Undecided cases recognized as undecided</td><td>{share(summary.gaps.all)}</td></tr>
            <tr><td className="indent">open questions the classifier is told about</td><td>{share(summary.gaps.told)}</td></tr>
            <tr><td className="indent">open questions it is not told about</td><td>{share(summary.gaps.not_told)}</td></tr>
            <tr><td className="indent">missing context</td><td>{share(summary.gaps.missing_context)}</td></tr>
            {KINDS.map((kind) => (
              <tr key={kind}><td>{kind}</td><td>{share(summary.by_kind[kind])}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card">
        <h3>Same content, different position or context</h3>
        <table>
          <tbody>
            {Object.entries(summary.sets).map(([name, members]) => (
              <tr key={name}>
                <td>{name}</td>
                <td className="mono">{members.cases.join(", ")}</td>
                <td>{members.all_right ? "all right" : <b className="wrong">not all right</b>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card">
        <h3>Every case. Click one to open it.</h3>
        <table className="rows">
          <thead>
            <tr><th>Case</th><th>Kind</th><th>My label</th><th>Classifier</th><th>Guardrail</th><th>What the classifier said</th></tr>
          </thead>
          <tbody>
            {summary.rows.map((row) => (
              <tr key={row.id} className={row.right ? "" : "row-wrong"} onClick={() => open(row.id)}>
                <td className="mono">{row.id}</td>
                <td>{row.kind}</td>
                <td><Badge verdict={row.gold} /></td>
                <td><Badge verdict={row.predicted} /></td>
                <td>{row.action}</td>
                <td className="small">{row.analysis}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Just enough Markdown to show policy.md: headings, lists, tables, bold and code.
function inline(text) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) => {
    if (part.startsWith("**")) return <b key={index}>{part.slice(2, -2)}</b>;
    if (part.startsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    return part;
  });
}

function Markdown({ text }) {
  const lines = text.split("\n");
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const start = i;
    if (!line.trim()) {
      i += 1;
    } else if (line.startsWith("# ")) {
      blocks.push(<h2 key={start}>{inline(line.slice(2))}</h2>);
      i += 1;
    } else if (line.startsWith("## ")) {
      blocks.push(<h3 key={start}>{inline(line.slice(3))}</h3>);
      i += 1;
    } else if (line.startsWith("- ")) {
      const items = [];
      while (i < lines.length && lines[i].startsWith("- ")) {
        items.push(<li key={i}>{inline(lines[i].slice(2))}</li>);
        i += 1;
      }
      blocks.push(<ul key={start}>{items}</ul>);
    } else if (line.startsWith("|")) {
      const rows = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        rows.push(lines[i].split("|").slice(1, -1).map((cell) => cell.trim()));
        i += 1;
      }
      const [head, , ...body] = rows;
      blocks.push(
        <table key={start}>
          <thead>
            <tr>{head.map((cell, k) => <th key={k}>{inline(cell)}</th>)}</tr>
          </thead>
          <tbody>
            {body.map((row, j) => (
              <tr key={j}>{row.map((cell, k) => <td key={k}>{inline(cell)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      );
    } else {
      blocks.push(<p key={start}>{inline(line)}</p>);
      i += 1;
    }
  }
  return <div className="markdown">{blocks}</div>;
}

function Policy({ policy }) {
  return (
    <div>
      <div className="card">
        <div className="label">Shown to the classifier, word for word</div>
        <Markdown text={policy.shown} />
      </div>
      <div className="card hidden-part">
        <div className="label">Not shown to the classifier</div>
        <Markdown text={policy.hidden} />
      </div>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("try");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState("");

  useEffect(() => {
    Promise.all([api("/api/config"), api("/api/cases"), api("/api/policy"), api("/api/results")])
      .then(([config, cases, policy, results]) => setData({ config, cases, policy, results }))
      .catch((problem) => setError(problem.message));
  }, []);

  if (error) return <div className="page"><p className="error">{error}</p></div>;
  if (!data) return <div className="page">Loading...</div>;
  const { config, cases, policy, results } = data;

  return (
    <div className="page">
      <div className="header">
        <div>
          <h1>Policy alignment classifier</h1>
          <div className="muted">One agent trace event in, one verdict out. Policy: Skyfern Travel support agent.</div>
        </div>
        <div className={`mode ${config.configured ? "mode-on" : "mode-off"}`}>
          <b>{config.configured ? config.model : "No model configured"}</b>
          <span>{config.configured ? `through ${config.provider}` : "add a key to .env"}</span>
        </div>
      </div>
      {!config.configured && (
        <div className="banner">
          No model is configured, so classifying will answer with an error. Copy <code>.env.example</code> to <code>.env</code>,
          add a key and restart.
        </div>
      )}
      <div className="tabs">
        {[["try", "Classify an event"], ["results", "Evaluation"], ["policy", "Policy"]].map(([id, title]) => (
          <button key={id} className={`tab ${tab === id ? "tab-active" : ""}`} onClick={() => setTab(id)}>
            {title}
          </button>
        ))}
      </div>
      {/* The first tab stays mounted so that what was typed survives a look at another tab. */}
      <div style={{ display: tab === "try" ? "block" : "none" }}>
        <TryIt cases={cases} openId={openId} />
      </div>
      {tab === "results" && (
        <Results
          results={results}
          open={(id) => {
            setOpenId(id);
            setTab("try");
          }}
        />
      )}
      {tab === "policy" && <Policy policy={policy} />}
    </div>
  );
}
