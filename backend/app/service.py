"""Service layer: DB access <-> pandas DataFrame and plan persistence."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Sample, SplitAssignment, SplitPlan, Subject
from .splitter import SplitParams, build_split


def samples_to_dataframe(db: Session) -> pd.DataFrame:
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

    data = []
    for r in rows:
        data.append(
            {
                "sample_code": r.sample_code,
                "kind": r.kind,
                "label": r.label,
                "collected_at": pd.to_datetime(r.collected_at),
                "subject_key": r.subject_key,
                "source_sample_code": r.source_ref,
            }
        )
    return pd.DataFrame(
        data,
        columns=[
            "sample_code",
            "kind",
            "label",
            "collected_at",
            "subject_key",
            "source_sample_code",
        ],
    )


def upsert_subject(db: Session, subject_key: str, display_name: str | None = None) -> Subject:
    obj = db.execute(
        select(Subject).where(Subject.subject_key == subject_key)
    ).scalar_one_or_none()
    if obj is None:
        obj = Subject(subject_key=subject_key, display_name=display_name)
        db.add(obj)
        db.flush()
    return obj


def create_sample(db: Session, payload: dict) -> Sample:
    existing = db.execute(
        select(Sample).where(Sample.sample_code == payload["sample_code"])
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError(f"sample_code already exists: {payload['sample_code']}")

    subject = None
    if payload.get("subject_key"):
        subject = upsert_subject(db, payload["subject_key"])

    # Soft reference by code: dangling sources are stored unresolved so the
    # planner can flag them rather than silently dropping provenance.
    sample = Sample(
        sample_code=payload["sample_code"],
        kind=payload["kind"],
        label=payload["label"],
        collected_at=payload["collected_at"],
        subject_id=subject.id if subject else None,
        source_ref=payload.get("source_sample_code"),
        note=payload.get("note"),
    )
    db.add(sample)
    db.commit()
    db.refresh(sample)
    return sample


def preview_split(db: Session, req) -> tuple[SplitPlan, dict]:
    df = samples_to_dataframe(db)
    params = SplitParams(
        cutoff_date=datetime.combine(req.cutoff_date, datetime.min.time()),
        target_eval_ratio=req.target_eval_ratio,
        seed=req.seed,
        cutoff_policy=req.cutoff_policy,
        target_label_ratios=req.target_label_ratios,
        subject_field=req.subject_field,
    )
    result = build_split(df, params)

    plan = SplitPlan(
        name=req.name,
        status="preview",
        cutoff_date=req.cutoff_date,
        subject_field=req.subject_field,
        target_eval_ratio=req.target_eval_ratio,
        target_label_ratios=req.target_label_ratios,
        seed=req.seed,
        cutoff_policy=req.cutoff_policy,
        stats=result["stats"],
    )
    db.add(plan)
    db.flush()

    code_to_id = dict(
        db.execute(select(Sample.sample_code, Sample.id)).all()
    )
    for item in result["assignments"]:
        db.add(
            SplitAssignment(
                plan_id=plan.id,
                sample_id=code_to_id[item["sample_code"]],
                effective_subject_key=item["effective_subject_key"],
                assignment=item["assignment"],
                reasons=item["reasons"],
                inherited=item["inherited"],
            )
        )
    db.commit()
    db.refresh(plan)
    return plan, result


def confirm_plan(db: Session, plan_id: str) -> SplitPlan:
    plan = db.get(SplitPlan, plan_id)
    if plan is None:
        raise KeyError(plan_id)
    if plan.status != "preview":
        raise ValueError("plan already confirmed")
    plan.status = "confirmed"
    plan.confirmed_at = datetime.utcnow()
    db.commit()
    db.refresh(plan)
    return plan


def plan_detail(db: Session, plan_id: str) -> dict:
    plan = db.get(SplitPlan, plan_id)
    if plan is None:
        raise KeyError(plan_id)
    assigns = db.execute(
        select(SplitAssignment, Sample)
        .join(Sample, SplitAssignment.sample_id == Sample.id)
        .where(SplitAssignment.plan_id == plan_id)
        .order_by(Sample.sample_code)
    ).all()
    rows = []
    for a, s in assigns:
        rows.append(
            {
                "sample_code": s.sample_code,
                "kind": s.kind,
                "label": s.label,
                "collected_at": s.collected_at.isoformat(),
                "assignment": a.assignment,
                "reasons": a.reasons,
                "inherited": a.inherited,
                "effective_subject_key": a.effective_subject_key,
            }
        )
    return {"plan": _plan_dict(plan), "assignments": rows}


def _plan_dict(plan: SplitPlan) -> dict:
    return {
        "id": plan.id,
        "name": plan.name,
        "status": plan.status,
        "cutoff_date": str(plan.cutoff_date),
        "subject_field": plan.subject_field,
        "target_eval_ratio": plan.target_eval_ratio,
        "target_label_ratios": plan.target_label_ratios,
        "seed": plan.seed,
        "cutoff_policy": plan.cutoff_policy,
        "stats": plan.stats,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
    }


def list_plans(db: Session) -> list[dict]:
    plans = db.execute(select(SplitPlan).order_by(SplitPlan.created_at.desc())).scalars()
    return [_plan_dict(p) for p in plans]
