"""Load demo reports (deterministic rule checks only, no AI call).

Run from the backend folder with the venv active:  python seed_demo.py
Safe to run more than once: it skips if the demo equipment already exists.
"""
from app import models as m
from app.database import SessionLocal, init_db
from app.schemas import ReportIn
from app.services import create_report

DEMO = [
    {
        "equipment_type": "pump",
        "identifier": "DEMO-PUMP-1",
        "issue_description": "Loud vibration and a hot bearing housing since the pump was restarted.",
        "operating_events": [
            {"time": "2026-10-06T08:00", "event": "Restart after power cut"},
            {"time": "2026-10-06T08:30", "event": "Suction strainer cleaned"},
        ],
        "sensor_readings": [
            {"name": "bearing_temp", "value": 70, "unit": "C", "source": "panel gauge"},
            {"name": "bearing_temp", "value": 97, "unit": "C", "source": "handheld probe"},
            {"name": "vibration", "value": 8.2, "unit": "mm/s"},
            {"name": "suction_pressure", "value": 0.4, "unit": "bar"},
        ],
    },
    {
        "equipment_type": "compressor",
        "identifier": "DEMO-COMP-1",
        "issue_description": "Oil is showing up in the downstream air line and the unit runs hot.",
        "operating_events": [{"time": "2026-10-05T14:00", "event": "Ambient temperature above 40 C in the plant room"}],
        "sensor_readings": [
            {"name": "discharge_temp", "value": 118, "unit": "C"},
            {"name": "discharge_pressure", "value": None, "unit": "bar"},
        ],
    },
    {
        "equipment_type": "motor",
        "identifier": "DEMO-MOT-1",
        "issue_description": "Motor trips intermittently a few seconds after starting.",
        "operating_events": [],
        "sensor_readings": [
            {"name": "bearing_temp", "value": 150, "unit": "F"},
            {"name": "vibration", "value": 0.2, "unit": "in/s"},
            {"name": "current_imbalance_pct", "value": 3, "unit": "%"},
            {"name": "winding_temp", "value": None, "unit": "C"},
        ],
    },
]


def main() -> None:
    init_db()
    ids = [d["identifier"] for d in DEMO]
    with SessionLocal() as db:
        if db.query(m.Equipment).filter(m.Equipment.identifier.in_(ids)).count():
            print("Demo data already present; nothing to do.")
            return
        for d in DEMO:
            report = create_report(db, ReportIn(**d))
            print(f"Created report #{report.id} for {d['equipment_type']} {d['identifier']}")


if __name__ == "__main__":
    main()