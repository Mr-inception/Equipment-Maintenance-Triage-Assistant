import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Banner, Evidence, fmt } from "../ui";
import WorkOrderCard from "./WorkOrderCard";

function TriageResult({ run }) {
  const res = run.result;
  const retrieved = res?.retrieved || [];

  if (run.status !== "success") {
    return (
      <>
        <Banner kind="error" title={run.status === "retrieval_failed" ? "Manual retrieval failed" : "AI triage failed"}>
          {run.error_message}
        </Banner>
        {retrieved.length > 0 && (
          <p className="hint">Manual sections that were retrieved before the failure: {retrieved.map((r) => r.id).join(", ")}</p>
        )}
      </>
    );
  }

  const pr = res.suggested_priority;
  return (
    <>
      <Banner kind="info">{res.disclaimer}</Banner>
      {res.warnings?.map((w, i) => <Banner key={i} kind="warn">{w}</Banner>)}

      <h4>Possible causes (not confirmed)</h4>
      {res.possible_causes.length === 0 && <p className="hint">No possible causes with valid citations.</p>}
      <ul className="plain">
        {res.possible_causes.map((c, i) => (
          <li key={i}>
            <strong>{c.cause}</strong> <Badge status={c.likelihood} />
            <div>{c.reasoning}</div>
            <Evidence items={c.evidence} retrieved={retrieved} />
          </li>
        ))}
      </ul>

      <h4>Follow-up questions</h4>
      <ul className="plain">
        {res.follow_up_questions.map((q, i) => (
          <li key={i}>{q.question}{q.why && <div className="hint">{q.why}</div>}</li>
        ))}
      </ul>

      <h4>Suggested inspection steps</h4>
      <ol>
        {res.inspection_steps.map((s, i) => (
          <li key={i}>{s.step} <Evidence items={s.evidence} retrieved={retrieved} /></li>
        ))}
      </ol>

      <h4>Suggested priority</h4>
      <p>
        <Badge status={pr.level} />
        {pr.adjusted && <span className="hint"> (AI suggested {pr.ai_level}; raised by deterministic checks)</span>}
      </p>
      <p>{pr.rationale} <Evidence items={pr.evidence} retrieved={retrieved} /></p>

      <details>
        <summary>Manual sections retrieved ({retrieved.length})</summary>
        <ul className="plain">
          {retrieved.map((r) => (
            <li key={r.id}><span className="chip manual">{r.id}</span> {r.title} <span className="hint">({r.reason})</span></li>
          ))}
        </ul>
      </details>
    </>
  );
}

export default function ReportDetail({ id, tech, onOpenEquipment }) {
  const [report, setReport] = useState(null);
  const [runs, setRuns] = useState([]);
  const [orders, setOrders] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [kind, setKind] = useState("observation");
  const [text, setText] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    try {
      const [r, t, w] = await Promise.all([api.getReport(id), api.triageRuns(id), api.workOrders(id)]);
      setReport(r);
      setRuns(t);
      setOrders(w);
    } catch (e) {
      setError(e.message);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const needTech = () => {
    if (tech.trim()) return true;
    setError("Enter your name in the Technician field at the top first.");
    return false;
  };

  const runTriage = async () => {
    setError("");
    setBusy(true);
    try {
      await api.triage(id);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (fid) => {
    if (!needTech()) return;
    setError("");
    try {
      await api.confirmFinding(fid, tech.trim());
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  const addFinding = async (e) => {
    e.preventDefault();
    if (!needTech()) return;
    setError("");
    try {
      await api.addFinding(id, { kind, text: text.trim(), recorded_by: tech.trim(), evidence_note: note.trim() || null });
      setText("");
      setNote("");
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  if (!report) return error ? <Banner kind="error">{error}</Banner> : <p>Loading report...</p>;

  const latest = runs[0];
  const confirmedFromIds = new Set(
    report.findings
      .filter((f) => f.kind === "confirmed_finding")
      .flatMap((f) => (f.evidence || []).filter((e) => e.type === "finding").map((e) => e.id))
  );
  const group = (k) => report.findings.filter((f) => f.kind === k);
  const rules = report.rules;

  return (
    <section>
      <div className="head">
        <h2>
          Report #{report.id}: {report.equipment.equipment_type} {report.equipment.identifier}{" "}
          <Badge status={report.status} />
        </h2>
        <button className="ghost" onClick={() => onOpenEquipment(report.equipment.id)}>View equipment history</button>
      </div>
      {error && <Banner kind="error">{error}</Banner>}

      <div className="card">
        <p>{report.issue_description}</p>
        <p className="hint">Reported {fmt(report.created_at)}</p>
        <h4>Recent operating events</h4>
        {report.operating_events.length === 0 ? <p className="hint">None reported.</p> : (
          <ul className="plain">
            {report.operating_events.map((e, i) => (
              <li key={i}><span className="chip event">EVENT-{i + 1}</span> {e.time && <span className="hint">{e.time} </span>}{e.event}</li>
            ))}
          </ul>
        )}
      </div>

      <div className="card">
        <h3>Threshold checks (deterministic rules)</h3>
        {rules.note && <Banner kind="warn">{rules.note}</Banner>}
        {rules.results.length === 0 ? <p className="hint">No sensor readings were provided.</p> : (
          <table className="table">
            <thead><tr><th>Sensor</th><th>Status</th><th>Details</th></tr></thead>
            <tbody>
              {rules.results.map((r) => (
                <tr key={r.sensor}>
                  <td>{r.label}</td>
                  <td><Badge status={r.status} /></td>
                  <td>{r.message} {r.citation && <span className="chip manual">{r.citation}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {rules.not_provided.length > 0 && (
          <p className="hint">No reading provided for: {rules.not_provided.join(", ")}</p>
        )}
        <p>Minimum priority from rules: {rules.priority_floor ? <Badge status={rules.priority_floor} /> : <span className="hint">none</span>}</p>
      </div>

      <div className="card">
        <div className="head">
          <h3>AI triage</h3>
          <button disabled={busy} onClick={runTriage}>{busy ? "Running..." : latest ? "Run triage again" : "Run AI triage"}</button>
        </div>
        {!latest && <p className="hint">Triage has not been run for this report yet.</p>}
        {latest && (
          <>
            <p className="hint">Latest run #{latest.id} at {fmt(latest.created_at)} <Badge status={latest.status} /> {runs.length > 1 && `(${runs.length} runs total)`}</p>
            <TriageResult run={latest} />
          </>
        )}
      </div>

      <div className="card">
        <h3>Findings</h3>
        <div className="cols">
          <div>
            <h4>Observations</h4>
            <p className="hint">Facts from rule checks or technicians.</p>
            <ul className="plain">
              {group("observation").map((f) => (
                <li key={f.id}>{f.text} <span className="hint">[{f.origin}]</span> <Evidence items={f.evidence} /></li>
              ))}
            </ul>
          </div>
          <div>
            <h4>Possible causes</h4>
            <p className="hint">AI hypotheses. Not confirmed.</p>
            <ul className="plain">
              {group("possible_cause").filter((f) => !f.superseded).map((f) => (
                <li key={f.id}>
                  {f.text} <Evidence items={f.evidence} />
                  {confirmedFromIds.has(f.id)
                    ? <div className="hint">Confirmed by a technician</div>
                    : f.duplicate_of_confirmed
                    ? <div className="hint">Already confirmed by a technician (see Confirmed findings)</div>
                    : <div><button className="ghost" onClick={() => confirm(f.id)}>Confirm as finding</button></div>}
                </li>
              ))}
            </ul>
            {group("possible_cause").some((f) => f.superseded) && (
              <details>
                <summary>Previous run suggestions</summary>
                <ul className="plain">
                  {group("possible_cause").filter((f) => f.superseded).map((f) => (
                    <li key={f.id}>
                      {f.text} <Evidence items={f.evidence} />
                      {confirmedFromIds.has(f.id)
                        ? <div className="hint">Confirmed by a technician</div>
                        : f.duplicate_of_confirmed
                        ? <div className="hint">Already confirmed by a technician (see Confirmed findings)</div>
                        : <div><button className="ghost" onClick={() => confirm(f.id)}>Confirm as finding</button></div>}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
          <div>
            <h4>Confirmed findings</h4>
            <p className="hint">Technician-verified only.</p>
            <ul className="plain">
              {group("confirmed_finding").map((f) => (
                <li key={f.id}>{f.text} <Evidence items={f.evidence} /></li>
              ))}
            </ul>
          </div>
        </div>

        <form onSubmit={addFinding} className="form">
          <h4>Add a technician finding</h4>
          <div className="row">
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="observation">Observation</option>
              <option value="confirmed_finding">Confirmed finding</option>
            </select>
            <input className="grow" value={text} onChange={(e) => setText(e.target.value)} placeholder="What did you find?" />
          </div>
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Evidence note (optional)" />
          <button type="submit" disabled={text.trim().length < 3}>Add finding</button>
        </form>
      </div>

      {latest?.status === "success" && latest.result?.proposed_work_order && latest.result?.work_order?.reused && (
        <div className="card">
          <h3>New AI proposal (not applied)</h3>
          <p className="hint">The existing draft work order was kept. The AI did not change or approve it.</p>
          <p>
            <strong>{latest.result.proposed_work_order.title}</strong>{" "}
            <Badge status={latest.result.proposed_work_order.priority} />
          </p>
          <pre className="wrap">{latest.result.proposed_work_order.description}</pre>
          <Evidence items={latest.result.proposed_work_order.evidence} retrieved={latest.result.retrieved || []} />
        </div>
      )}

      <h3>Work orders</h3>
      {orders.length === 0 && <p className="hint">No work order yet. A draft is created when AI triage succeeds.</p>}
      {orders.map((wo) => (
        <WorkOrderCard key={`${wo.id}-${wo.updated_at}`} wo={wo} tech={tech} onChanged={load} onError={setError} />
      ))}
    </section>
  );
}
