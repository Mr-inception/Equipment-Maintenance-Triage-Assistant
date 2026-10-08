from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
from ..findings import add_finding, confirm_finding, finding_detail
from ..schemas_workflow import ApproveIn, ConfirmIn, FindingIn, RejectIn, WorkOrderEdit
from ..workorders import (
    ConflictError, approve_work_order, edit_work_order, reject_work_order, work_order_detail,
)

router = APIRouter(prefix="/api", tags=["workflow"])


def _wo(db: Session, work_order_id: int) -> m.WorkOrder:
    wo = db.get(m.WorkOrder, work_order_id)
    if wo is None:
        raise HTTPException(status_code=404, detail="Work order not found")
    return wo


def _conflict(exc: ConflictError):
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/reports/{report_id}/work-orders")
def report_work_orders(report_id: int, db: Session = Depends(get_db)):
    if db.get(m.IssueReport, report_id) is None:
        raise HTTPException(status_code=404, detail="Report not found")
    rows = (
        db.query(m.WorkOrder).filter(m.WorkOrder.report_id == report_id)
        .order_by(m.WorkOrder.id.desc()).all()
    )
    return [work_order_detail(w) for w in rows]


@router.get("/work-orders/{work_order_id}")
def get_work_order(work_order_id: int, db: Session = Depends(get_db)):
    return work_order_detail(_wo(db, work_order_id))


@router.patch("/work-orders/{work_order_id}")
def patch_work_order(work_order_id: int, body: WorkOrderEdit, db: Session = Depends(get_db)):
    wo = _wo(db, work_order_id)
    try:
        edit_work_order(db, wo, body.model_dump(exclude={"edited_by"}), body.edited_by)
    except ConflictError as exc:
        raise _conflict(exc)
    return work_order_detail(wo)


@router.post("/work-orders/{work_order_id}/approve")
def approve(work_order_id: int, body: ApproveIn, db: Session = Depends(get_db)):
    wo = _wo(db, work_order_id)
    try:
        approve_work_order(db, wo, body.decided_by)
    except ConflictError as exc:
        raise _conflict(exc)
    return work_order_detail(wo)


@router.post("/work-orders/{work_order_id}/reject")
def reject(work_order_id: int, body: RejectIn, db: Session = Depends(get_db)):
    wo = _wo(db, work_order_id)
    try:
        reject_work_order(db, wo, body.decided_by, body.reason)
    except ConflictError as exc:
        raise _conflict(exc)
    return work_order_detail(wo)


@router.post("/reports/{report_id}/findings", status_code=201)
def create_finding(report_id: int, body: FindingIn, db: Session = Depends(get_db)):
    report = db.get(m.IssueReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    f = add_finding(db, report, body.kind, body.text, body.recorded_by, body.evidence_note)
    return finding_detail(f)


@router.post("/findings/{finding_id}/confirm", status_code=201)
def confirm(finding_id: int, body: ConfirmIn, db: Session = Depends(get_db)):
    finding = db.get(m.Finding, finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    try:
        new = confirm_finding(db, finding, body.confirmed_by, body.notes)
    except ConflictError as exc:
        raise _conflict(exc)
    return finding_detail(new)


@router.get("/equipment")
def list_equipment(db: Session = Depends(get_db)):
    rows = db.query(m.Equipment).order_by(m.Equipment.equipment_type, m.Equipment.identifier).all()
    return [
        {
            "id": e.id, "equipment_type": e.equipment_type, "identifier": e.identifier,
            "report_count": len(e.reports),
        }
        for e in rows
    ]


@router.get("/equipment/{equipment_id}/history")
def equipment_history(equipment_id: int, limit: int = Query(200, ge=1, le=500),
                      db: Session = Depends(get_db)):
    eq = db.get(m.Equipment, equipment_id)
    if eq is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    reports = sorted(eq.reports, key=lambda r: r.id, reverse=True)
    work_orders = (
        db.query(m.WorkOrder).join(m.IssueReport).filter(m.IssueReport.equipment_id == eq.id)
        .order_by(m.WorkOrder.id.desc()).all()
    )
    confirmed = (
        db.query(m.Finding).join(m.IssueReport)
        .filter(m.IssueReport.equipment_id == eq.id, m.Finding.kind == m.FindingKind.confirmed_finding)
        .order_by(m.Finding.id.desc()).all()
    )
    events = (
        db.query(m.HistoryEvent).filter(m.HistoryEvent.equipment_id == eq.id)
        .order_by(m.HistoryEvent.id.desc()).limit(limit).all()
    )
    return {
        "equipment": {"id": eq.id, "equipment_type": eq.equipment_type, "identifier": eq.identifier},
        "reports": [
            {
                "id": r.id, "issue_description": r.issue_description, "status": r.status.value,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reports
        ],
        "work_orders": [work_order_detail(w) for w in work_orders],
        "confirmed_findings": [finding_detail(f) for f in confirmed],
        "events": [
            {
                "id": e.id, "report_id": e.report_id, "event_type": e.event_type, "actor": e.actor,
                "detail": e.detail, "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }
