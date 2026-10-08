from sqlalchemy.orm import Session

from . import models as m
from .findings import confirmed_cause_ids, is_superseded, latest_successful_run_id
from .rules import normalize_sensor_name, run_rules
from .schemas import ReportIn


def _evidence(r) -> list:
    ev = []
    if r.citation:
        ev.append({"type": "manual", "id": r.citation})
    ev.append({"type": "sensor", "name": r.sensor, "values": r.values, "unit": r.unit})
    return ev


def create_report(db: Session, payload: ReportIn) -> m.IssueReport:
    etype = payload.equipment_type.strip().lower()
    ident = payload.identifier.strip().upper()

    eq = (
        db.query(m.Equipment)
        .filter(m.Equipment.equipment_type == etype, m.Equipment.identifier == ident)
        .one_or_none()
    )
    if eq is None:
        eq = m.Equipment(equipment_type=etype, identifier=ident)
        db.add(eq)
        db.flush()

    report = m.IssueReport(
        equipment_id=eq.id,
        issue_description=payload.issue_description.strip(),
        operating_events=[e.model_dump() for e in payload.operating_events],
    )
    db.add(report)
    db.flush()

    raw_readings = []
    for s in payload.sensor_readings:
        name = normalize_sensor_name(s.name)
        db.add(
            m.SensorReading(
                report_id=report.id, name=name, value=s.value, unit=s.unit,
                source=s.source, recorded_at=s.recorded_at,
            )
        )
        raw_readings.append({"name": name, "value": s.value, "unit": s.unit})

    summary = run_rules(etype, raw_readings)
    for r in summary.results:
        db.add(
            m.Finding(
                report_id=report.id,
                kind=m.FindingKind.observation,
                origin=m.FindingOrigin.rule,
                text=r.message,
                evidence=_evidence(r),
            )
        )

    db.add(
        m.HistoryEvent(
            equipment_id=eq.id, report_id=report.id, event_type="report_created",
            actor="reporter", detail={"issue": report.issue_description},
        )
    )
    db.add(
        m.HistoryEvent(
            equipment_id=eq.id, report_id=report.id, event_type="rules_evaluated",
            actor="system",
            detail={
                "overall_severity": summary.overall_severity,
                "data_issue_count": summary.data_issue_count,
            },
        )
    )
    db.commit()
    return report


def report_detail(report: m.IssueReport) -> dict:
    eq = report.equipment
    readings = sorted(report.sensor_readings, key=lambda r: r.id)
    summary = run_rules(
        eq.equipment_type,
        [{"name": r.name, "value": r.value, "unit": r.unit} for r in readings],
    )
    findings = sorted(report.findings, key=lambda f: f.id)
    latest_run_id = latest_successful_run_id(report)
    confirmed_ids = confirmed_cause_ids(findings)
    return {
        "id": report.id,
        "equipment": {"id": eq.id, "equipment_type": eq.equipment_type, "identifier": eq.identifier},
        "issue_description": report.issue_description,
        "operating_events": report.operating_events,
        "status": report.status.value,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "sensor_readings": [
            {
                "name": r.name, "value": r.value, "unit": r.unit, "source": r.source,
                "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
            }
            for r in readings
        ],
        "rules": summary.to_dict(),
        "findings": [
            {
                "id": f.id, "kind": f.kind.value, "origin": f.origin.value,
                "text": f.text, "evidence": f.evidence,
                "superseded": is_superseded(f, latest_run_id, confirmed_ids),
            }
            for f in findings
        ],
    }
