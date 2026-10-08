import { useEffect, useState } from "react";
import { api } from "./api";
import { Banner } from "./ui";
import ReportForm from "./components/ReportForm";
import ReportList from "./components/ReportList";
import ReportDetail from "./components/ReportDetail";
import EquipmentHistory from "./components/EquipmentHistory";

export default function App() {
  const [view, setView] = useState({ name: "reports" });
  const [tech, setTech] = useState(() => {
    try {
      return localStorage.getItem("technician_name") || "";
    } catch {
      return "";
    }
  });
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState("");

  useEffect(() => {
    api.health().then(setHealth).catch((e) => setHealthError(e.message));
  }, []);

  const updateTech = (v) => {
    setTech(v);
    try {
      localStorage.setItem("technician_name", v);
    } catch {
      /* storage unavailable */
    }
  };

  const go = (name, id) => setView({ name, id });

  return (
    <div className="app">
      <header className="topbar">
        <h1>Equipment Maintenance Triage</h1>
        <nav>
          <button className={view.name === "reports" ? "active" : ""} onClick={() => go("reports")}>Reports</button>
          <button className={view.name === "new" ? "active" : ""} onClick={() => go("new")}>New report</button>
          <button className={view.name === "equipment" ? "active" : ""} onClick={() => go("equipment")}>Equipment history</button>
        </nav>
        <label className="tech">
          Technician
          <input value={tech} onChange={(e) => updateTech(e.target.value)} placeholder="Your name" />
        </label>
      </header>

      <main>
        {healthError && <Banner kind="error" title="Backend unreachable">{healthError}</Banner>}
        {health && !health.llm_configured && (
          <Banner kind="warn" title="AI is not configured">
            No Anthropic API key is set on the server, so AI triage will fail. Rule checks, history and work order
            handling still work.
          </Banner>
        )}
        {health && health.knowledge_base.status !== "ok" && (
          <Banner kind="error" title="Knowledge base unavailable">
            Manuals could not be loaded, so triage cannot retrieve manual sections.
          </Banner>
        )}

        {view.name === "reports" && <ReportList onOpen={(id) => go("report", id)} />}
        {view.name === "new" && <ReportForm onCreated={(id) => go("report", id)} />}
        {view.name === "report" && (
          <ReportDetail key={view.id} id={view.id} tech={tech} onOpenEquipment={(id) => go("equipment", id)} />
        )}
        {view.name === "equipment" && <EquipmentHistory initialId={view.id} onOpenReport={(id) => go("report", id)} />}
      </main>
    </div>
  );
}
