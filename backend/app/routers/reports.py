import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
from ..schemas import ReportIn
from ..services import create_report, report_detail
from ..triage import run_detail, run_triage

logger = logging.getLogger("triage.reports")
router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.post("", status_code=201)
def create(payload: ReportIn, db: Session = Depends(get_db)):
    report = create_report(db, payload)
    logger.info("Report %s created for %s", report.id, report.equipment_id)
    return report_detail(report)


@router.post("/{report_id}/triage")
def triage(report_id: int, db: Session = Depends(get_db)):
    try:
        return run_triage(db, report_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Report not found")


@router.get("/{report_id}/triage-runs")
def triage_runs(report_id: int, db: Session = Depends(get_db)):
    if db.get(m.IssueReport, report_id) is None:
        raise HTTPException(status_code=404, detail="Report not found")
    runs = (
        db.query(m.TriageRun)
        .filter(m.TriageRun.report_id == report_id)
        .order_by(m.TriageRun.id.desc())
        .all()
    )
    return [run_detail(r) for r in runs]


@router.get("/{report_id}")
def get_one(report_id: int, db: Session = Depends(get_db)):
    report = db.get(m.IssueReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report_detail(report)


@router.get("")
def list_reports(
    equipment_type: Optional[str] = None,
    identifier: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(m.IssueReport).join(m.Equipment)
    if equipment_type:
        q = q.filter(m.Equipment.equipment_type == equipment_type.strip().lower())
    if identifier:
        q = q.filter(m.Equipment.identifier == identifier.strip().upper())
    rows = q.order_by(m.IssueReport.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "equipment_type": r.equipment.equipment_type,
            "identifier": r.equipment.identifier,
            "issue_description": r.issue_description,
            "status": r.status.value,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
