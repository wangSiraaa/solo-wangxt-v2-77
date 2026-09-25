"""HTTP API: inventory management, split preview/confirm, demo reset."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import service
from ..db import get_session
from ..schemas import ConfirmRequest, SampleIn, SplitRequest
from ..seed import reset_demo

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/samples")
def list_samples(db: Session = Depends(get_session)):
    from sqlalchemy import select

    from ..models import Sample, Subject

    rows = db.execute(
        select(
            Sample.sample_code,
            Sample.kind,
            Sample.label,
            Sample.collected_at,
            Sample.source_ref,
            Subject.subject_key.label("subject_key"),
        )
        .outerjoin(Subject, Sample.subject_id == Subject.id)
        .order_by(Sample.sample_code)
    ).all()
    return [
        {
            "sample_code": r.sample_code,
            "kind": r.kind,
            "label": r.label,
            "collected_at": r.collected_at.isoformat(),
            "subject_key": r.subject_key,
            "source_sample_code": r.source_ref,
        }
        for r in rows
    ]


@router.post("/samples", status_code=201)
def add_sample(payload: SampleIn, db: Session = Depends(get_session)):
    try:
        sample = service.create_sample(db, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": sample.id, "sample_code": sample.sample_code}


@router.post("/demo/reset")
def demo_reset(db: Session = Depends(get_session)):
    return reset_demo(db)


@router.post("/splits/preview")
def split_preview(req: SplitRequest, db: Session = Depends(get_session)):
    try:
        plan, result = service.preview_split(db, req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "plan_id": plan.id,
        "params": result["params"],
        "stats": result["stats"],
        "assignments": result["assignments"],
    }


@router.post("/splits/confirm")
def split_confirm(req: ConfirmRequest, db: Session = Depends(get_session)):
    try:
        plan = service.confirm_plan(db, req.plan_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="plan not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return service._plan_dict(plan)


@router.get("/splits")
def split_list(db: Session = Depends(get_session)):
    return service.list_plans(db)


@router.get("/splits/{plan_id}")
def split_detail(plan_id: str, db: Session = Depends(get_session)):
    try:
        return service.plan_detail(db, plan_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="plan not found") from exc
