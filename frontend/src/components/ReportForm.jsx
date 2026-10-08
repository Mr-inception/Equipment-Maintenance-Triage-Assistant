import { useState } from "react";
import { api } from "../api";
import { Banner } from "../ui";

const SENSORS = {
  pump: [["bearing_temp", "C"], ["vibration", "mm/s"], ["suction_pressure", "bar"]],
  compressor: [["discharge_temp", "C"], ["discharge_pressure", "bar"], ["vibration", "mm/s"]],
  motor: [["winding_temp", "C"], ["bearing_temp", "C"], ["vibration", "mm/s"], ["current_imbalance_pct", "%"]],
};

export default function ReportForm({ onCreated }) {
  const [type, setType] = useState("pump");
  const [identifier, setIdentifier] = useState("");
  const [description, setDescription] = useState("");
  const [events, setEvents] = useState([{ time: "", event: "" }]);
  const [sensors, setSensors] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const suggestions = SENSORS[type] || [];
  const setEvent = (i, patch) => setEvents(events.map((e, k) => (k === i ? { ...e, ...patch } : e)));
  const setSensor = (i, patch) => setSensors(sensors.map((s, k) => (k === i ? { ...s, ...patch } : s)));
  const addSensor = (name = "", unit = "") => setSensors([...sensors, { name, value: "", unit }]);

  const onSensorName = (i, name) => {
    const match = suggestions.find(([n]) => n === name);
    setSensor(i, match && !sensors[i].unit ? { name, unit: match[1] } : { name });
  };

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (!identifier.trim()) return setError("Equipment identifier is required.");
    if (description.trim().length < 5) return setError("Describe the issue in at least 5 characters.");

    const sensor_readings = [];
    for (const s of sensors) {
      if (!s.name.trim()) continue;
      let value = null;
      if (s.value !== "") {
        value = Number(s.value);
        if (Number.isNaN(value)) return setError(`Sensor value for "${s.name}" must be a number.`);
      }
      sensor_readings.push({ name: s.name.trim(), value, unit: s.unit.trim() || null });
    }
    const operating_events = events
      .filter((x) => x.event.trim())
      .map((x) => ({ time: x.time || null, event: x.event.trim() }));

    setBusy(true);
    try {
      const report = await api.createReport({
        equipment_type: type,
        identifier: identifier.trim(),
        issue_description: description.trim(),
        operating_events,
        sensor_readings,
      });
      onCreated(report.id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="card form">
      <h2>Report an equipment problem</h2>
      {error && <Banner kind="error">{error}</Banner>}

      <div className="row">
        <label>
          Equipment type
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {Object.keys(SENSORS).map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label>
          Identifier
          <input value={identifier} onChange={(e) => setIdentifier(e.target.value)} placeholder="e.g. P-101" />
        </label>
      </div>

      <label>
        Issue description
        <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)}
          placeholder="What is wrong? What did you see, hear or measure?" />
      </label>

      <fieldset>
        <legend>Recent operating events</legend>
        {events.map((ev, i) => (
          <div className="row" key={i}>
            <input type="datetime-local" value={ev.time} onChange={(e) => setEvent(i, { time: e.target.value })} />
            <input className="grow" value={ev.event} placeholder="e.g. Restart after power cut"
              onChange={(e) => setEvent(i, { event: e.target.value })} />
            <button type="button" className="ghost" onClick={() => setEvents(events.filter((_, k) => k !== i))}>Remove</button>
          </div>
        ))}
        <button type="button" className="ghost" onClick={() => setEvents([...events, { time: "", event: "" }])}>
          + Add event
        </button>
      </fieldset>

      <fieldset>
        <legend>Sensor readings (optional)</legend>
        <p className="hint">Leave a value blank to record a missing reading. Add the same sensor twice to record conflicting readings.</p>
        <datalist id="sensor-names">
          {suggestions.map(([n]) => <option key={n} value={n} />)}
        </datalist>
        {sensors.map((s, i) => (
          <div className="row" key={i}>
            <input list="sensor-names" value={s.name} placeholder="sensor name"
              onChange={(e) => onSensorName(i, e.target.value)} />
            <input value={s.value} placeholder="value (blank = missing)" onChange={(e) => setSensor(i, { value: e.target.value })} />
            <input className="narrow" value={s.unit} placeholder="unit" onChange={(e) => setSensor(i, { unit: e.target.value })} />
            <button type="button" className="ghost" onClick={() => setSensors(sensors.filter((_, k) => k !== i))}>Remove</button>
          </div>
        ))}
        <div className="row">
          {suggestions.map(([n, u]) => (
            <button type="button" className="ghost" key={n} onClick={() => addSensor(n, u)}>+ {n}</button>
          ))}
          <button type="button" className="ghost" onClick={() => addSensor()}>+ Other</button>
        </div>
      </fieldset>

      <button type="submit" disabled={busy}>{busy ? "Submitting..." : "Submit report"}</button>
    </form>
  );
}
