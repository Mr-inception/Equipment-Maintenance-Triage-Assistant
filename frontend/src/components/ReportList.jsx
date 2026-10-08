import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Banner, fmt } from "../ui";

export default function ReportList({ onOpen }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.listReports().then(setRows).catch((e) => setError(e.message));
  }, []);

  if (error) return <Banner kind="error" title="Could not load reports">{error}</Banner>;
  if (!rows) return <p>Loading reports...</p>;
  if (!rows.length) return <p>No reports yet. Use "New report" to submit an equipment problem.</p>;

  return (
    <section>
      <h2>Reports</h2>
      <table className="table">
        <thead>
          <tr><th>#</th><th>Equipment</th><th>Issue</th><th>Status</th><th>Created</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="clickable" onClick={() => onOpen(r.id)}>
              <td>{r.id}</td>
              <td>{r.equipment_type} {r.identifier}</td>
              <td>{r.issue_description}</td>
              <td><Badge status={r.status} /></td>
              <td>{fmt(r.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
