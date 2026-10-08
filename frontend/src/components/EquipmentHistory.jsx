import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Banner, Evidence, fmt } from "../ui";

export default function EquipmentHistory({ initialId, onOpenReport }) {
  const [list, setList] = useState(null);
  const [selected, setSelected] = useState(initialId || null);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.listEquipment().then(setList).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setData(null);
    api.history(selected).then(setData).catch((e) => setError(e.message));
  }, [selected]);

  if (error) return <Banner kind="error">{error}</Banner>;
  if (!list) return <p>Loading equipment...</p>;
  if (!list.length) return <p>No equipment yet. Submit a report to create one.</p>;

  return (
    <section className="split">
      <aside className="card">
        <h3>Equipment</h3>
        <ul className="plain">
          {list.map((e) => (
            <li key={e.id}>
              <button className={`ghost ${selected === e.id ? "active" : ""}`} onClick={() => setSelected(e.id)}>
                {e.equipment_type} {e.identifier} ({e.report_count})
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <div>
        {!selected && <p>Select an equipment item to see its history.</p>}
        {selected && !data && <p>Loading history...</p>}
        {data && (
          <>
            <h2>{data.equipment.equipment_type} {data.equipment.identifier}</h2>

            <div className="card">
              <h3>Reports</h3>
              <ul className="plain">
                {data.reports.map((r) => (
                  <li key={r.id}>
                    <button className="link" onClick={() => onOpenReport(r.id)}>#{r.id}</button> {r.issue_description}{" "}
                    <Badge status={r.status} /> <span className="hint">{fmt(r.created_at)}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="card">
              <h3>Work orders</h3>
              {data.work_orders.length === 0 && <p className="hint">None yet.</p>}
              <ul className="plain">
                {data.work_orders.map((w) => (
                  <li key={w.id}>
                    #{w.id} {w.title} <Badge status={w.status} /> <Badge status={w.priority} />
                    {w.decided_by && <span className="hint"> by {w.decided_by}</span>}
                  </li>
                ))}
              </ul>
            </div>

            <div className="card">
              <h3>Confirmed findings</h3>
              {data.confirmed_findings.length === 0 && <p className="hint">None yet.</p>}
              <ul className="plain">
                {data.confirmed_findings.map((f) => (
                  <li key={f.id}>{f.text} <Evidence items={f.evidence} /></li>
                ))}
              </ul>
            </div>

            <div className="card">
              <h3>Audit trail</h3>
              <table className="table">
                <thead><tr><th>When</th><th>Event</th><th>By</th><th>Report</th></tr></thead>
                <tbody>
                  {data.events.map((e) => (
                    <tr key={e.id}>
                      <td>{fmt(e.created_at)}</td>
                      <td>{e.event_type.replace(/_/g, " ")}</td>
                      <td>{e.actor}</td>
                      <td>{e.report_id ? `#${e.report_id}` : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
