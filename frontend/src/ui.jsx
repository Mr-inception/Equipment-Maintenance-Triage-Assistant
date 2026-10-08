const STATUS_CLASS = {
  ok: "ok", warning: "warn", critical: "crit", missing: "muted", conflict: "crit-outline",
  unit_error: "muted", implausible: "muted", unknown_sensor: "muted",
  draft: "info", approved: "ok", rejected: "crit",
  success: "ok", ai_failed: "crit", retrieval_failed: "crit",
  open: "info", triaged: "ok", closed: "muted",
  low: "muted", medium: "info", high: "warn",
};

export function Badge({ status }) {
  return <span className={`badge ${STATUS_CLASS[status] || "muted"}`}>{String(status).replace(/_/g, " ")}</span>;
}

export function Banner({ kind = "info", title, children }) {
  return (
    <div className={`banner ${kind}`} role={kind === "error" ? "alert" : "status"}>
      {title && <strong>{title}</strong>}
      {children && <div>{children}</div>}
    </div>
  );
}

export function fmt(iso) {
  return iso ? new Date(iso).toLocaleString() : "";
}

export function Evidence({ items = [], retrieved = [] }) {
  const titles = Object.fromEntries(retrieved.map((r) => [r.id, r.title]));
  const norm = items.map((i) => {
    if (typeof i !== "string") return i;
    if (i === "ISSUE") return { type: "report" };
    if (i.startsWith("EVENT-")) return { type: "event", id: i };
    if (i.startsWith("SENSOR:")) return { type: "sensor", name: i.slice(7) };
    return { type: "manual", id: i };
  });
  if (!norm.length) return <span className="muted-text">no evidence recorded</span>;
  return (
    <span className="chips">
      {norm.map((e, idx) => {
        if (e.type === "manual")
          return <span key={idx} className="chip manual" title={titles[e.id] || "Manual section"}>{e.id}</span>;
        if (e.type === "event")
          return <span key={idx} className="chip event" title={e.text || "Operating event"}>{e.id}</span>;
        if (e.type === "report") return <span key={idx} className="chip event" title="Issue description from the report">issue description</span>;
        if (e.type === "sensor") return <span key={idx} className="chip sensor">sensor: {e.name}</span>;
        if (e.type === "finding") return <span key={idx} className="chip">finding #{e.id}</span>;
        return <span key={idx} className="chip" title={e.note || ""}>technician note</span>;
      })}
    </span>
  );
}
