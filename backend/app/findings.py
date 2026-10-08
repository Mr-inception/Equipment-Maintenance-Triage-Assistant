from sqlalchemy.orm import Session

from . import models as m
from .workorders import ConflictError


def normalize_cause_title(text: str) -> str:
    if not text:
        return ""
    idx = text.find(" (likelihood:")
    if idx != -1:
        title = text[:idx]
    else:
        title = text
    return title.strip().lower()


def confirmed_causes_by_title(findings) -> dict[str, tuple[int, int]]:
    by_id = {f.id: f for f in findings}
    mapping = {}
    for f in findings:
        if f.kind != m.FindingKind.confirmed_finding:
            continue
        for e in f.evidence or []:
            if e.get("type") == "finding" and e.get("id") is not None:
                orig_id = e["id"]
                orig_finding = by_id.get(orig_id)
                if orig_finding:
                    title = normalize_cause_title(orig_finding.text)
                    if title:
                        mapping[title] = (orig_id, f.id)
    return mapping


def confirmed_cause_ids(findings) -> set[int]:
    ids = set()
    for f in findings:
        if f.kind != m.FindingKind.confirmed_finding:
            continue
        for e in f.evidence or []:
            if e.get("type") == "finding" and e.get("id") is not None:
                ids.add(e["id"])
    return ids


def latest_successful_run_id(report: m.IssueReport):
    ids = [r.id for r in (report.triage_runs or []) if r.status == m.TriageStatus.success]
    return max(ids) if ids else None


def is_superseded(f: m.Finding, latest_run_id=None, confirmed_ids=None) -> bool:
    if f.kind != m.FindingKind.possible_cause:
        return False
    if confirmed_ids is None:
        confirmed_ids = confirmed_cause_ids(f.report.findings)
    if f.id in confirmed_ids:
        return False
    if latest_run_id is None:
        latest_run_id = latest_successful_run_id(f.report)
    if latest_run_id is None or f.triage_run_id is None:
        return False
    return f.triage_run_id != latest_run_id


def finding_detail(f: m.Finding, confirmed_by_title: dict[str, tuple[int, int]] | None = None) -> dict:
    d = {
        "id": f.id,
        "report_id": f.report_id,
        "kind": f.kind.value,
        "origin": f.origin.value,
        "text": f.text,
        "evidence": f.evidence,
        "created_at": f.created_at.isoformat() if f.created_at else None,
        "superseded": is_superseded(f),
    }
    if f.kind == m.FindingKind.possible_cause:
        if confirmed_by_title is None and f.report:
            confirmed_by_title = confirmed_causes_by_title(f.report.findings)
        is_dup = False
        cf_id = None
        if confirmed_by_title:
            norm = normalize_cause_title(f.text)
            if norm in confirmed_by_title:
                orig_id, conf_id = confirmed_by_title[norm]
                if f.id != orig_id:
                    is_dup = True
                    cf_id = conf_id
        d["duplicate_of_confirmed"] = is_dup
        d["confirmed_finding_id"] = cf_id
    return d


def add_finding(db: Session, report: m.IssueReport, kind: str, text: str,
                recorded_by: str, evidence_note=None) -> m.Finding:
    evidence = [{"type": "technician", "note": evidence_note}] if evidence_note else []
    f = m.Finding(
        report_id=report.id, kind=m.FindingKind(kind), origin=m.FindingOrigin.technician,
        text=text.strip(), evidence=evidence,
    )
    db.add(f)
    db.flush()
    db.add(
        m.HistoryEvent(
            equipment_id=report.equipment_id, report_id=report.id, event_type="finding_added",
            actor=recorded_by, detail={"finding_id": f.id, "kind": kind},
        )
    )
    db.commit()
    return f


def confirm_finding(db: Session, finding: m.Finding, confirmed_by: str, notes=None) -> m.Finding:
    if finding.kind != m.FindingKind.possible_cause:
        raise ConflictError("Only a possible cause can be confirmed.")
    for other in finding.report.findings:
        if other.kind == m.FindingKind.confirmed_finding and any(
            e.get("type") == "finding" and e.get("id") == finding.id for e in (other.evidence or [])
        ):
            raise ConflictError("This possible cause has already been confirmed.")

    conf_by_title = confirmed_causes_by_title(finding.report.findings)
    norm = normalize_cause_title(finding.text)
    if norm in conf_by_title:
        orig_id, _ = conf_by_title[norm]
        if finding.id != orig_id:
            raise ConflictError("A possible cause with this title has already been confirmed by a technician.")

    text = f"Confirmed by technician: {finding.text}"
    if notes:
        text += f" Notes: {notes.strip()}"
    new = m.Finding(
        report_id=finding.report_id, triage_run_id=finding.triage_run_id,
        kind=m.FindingKind.confirmed_finding, origin=m.FindingOrigin.technician,
        text=text, evidence=list(finding.evidence or []) + [{"type": "finding", "id": finding.id}],
    )
    db.add(new)
    db.flush()
    db.add(
        m.HistoryEvent(
            equipment_id=finding.report.equipment_id, report_id=finding.report_id,
            event_type="finding_confirmed", actor=confirmed_by,
            detail={"finding_id": new.id, "confirmed_from": finding.id},
        )
    )
    db.commit()
    return new
