"""Persistence helpers for split runs (manifest + seed storage)."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Assignment, Conflict, Sample, SplitRun
from .schemas import SampleIn
from .splitting import SplitParams, build_split, normalize_targets


def upsert_sample(db: Session, payload: SampleIn) -> Sample:
    sample = db.get(Sample, payload.id)
    if sample is None:
        sample = Sample(id=payload.id)
        db.add(sample)
    sample.label = payload.label
    sample.captured_at = payload.captured_at
    sample.subject_id = payload.subject_id or None
    sample.parent_id = payload.parent_id or None
    sample.kind = payload.kind
    db.flush()
    return sample


def parent_id_exists(db: Session, parent_id: str, *, exclude: str | None = None) -> bool:
    stmt = select(Sample.id).where(Sample.id == parent_id)
    if exclude:
        stmt = stmt.where(Sample.id != exclude)
    return db.execute(stmt).first() is not None


def create_run(db: Session, req, result: dict) -> SplitRun:
    target_ratios = normalize_targets(req.target_eval_ratio)
    run = SplitRun(
        cutoff=req.cutoff,
        subject_field=req.subject_field,
        target_ratios=target_ratios,
        seed=result["seed"],
        time_mode=req.time_mode,
        straddle_policy=req.straddle_policy,
        status="preview",
        summary=_summary(result, target_ratios),
    )
    db.add(run)
    db.flush()
    _persist_rows(db, run, result)
    db.flush()
    return run


def confirm_run(db: Session, run: SplitRun) -> SplitRun:
    run.status = "confirmed"
    run.confirmed_at = datetime.utcnow()
    db.flush()
    return run


def run_split(db: Session, req) -> tuple[SplitRun, dict]:
    samples = list(db.execute(select(Sample).order_by(Sample.id)).scalars())
    target_ratios = normalize_targets(req.target_eval_ratio)
    params = SplitParams(
        cutoff=req.cutoff,
        subject_field=req.subject_field,
        target_ratios=target_ratios,
        seed=req.seed,
        time_mode=req.time_mode,
        straddle_policy=req.straddle_policy,
    )
    result = build_split(samples, params)
    run = create_run(db, req, result)
    result_with_id = {
        **result,
        "run_id": run.id,
        "status": run.status,
        "cutoff": req.cutoff,
        "subject_field": req.subject_field,
        "target_ratios": target_ratios,
        "time_mode": req.time_mode,
        "straddle_policy": req.straddle_policy,
    }
    return run, result_with_id


def _summary(result: dict, target_ratios: dict) -> dict:
    return {
        "buckets": result["buckets"],
        "ratios": result["ratios"],
        "warnings": result["warnings"],
        "leakage_statement": result["leakage_statement"],
    }


def _persist_rows(db: Session, run: SplitRun, result: dict) -> None:
    for a in result["assignments"]:
        db.add(
            Assignment(
                run_id=run.id,
                sample_id=a["sample_id"],
                bucket=a["bucket"],
                root_subject=a["root_subject"],
                reason=a["reason"],
            )
        )
    for c in result["conflicts"]:
        db.add(
            Conflict(
                run_id=run.id,
                subject=c["subject"],
                conflict_type=c["conflict_type"],
                severity=c["severity"],
                detail=c["detail"],
                sample_ids=c["sample_ids"],
            )
        )


def serialize_run(run: SplitRun) -> dict:
    target_ratios = run.target_ratios or {}
    return {
        "run_id": run.id,
        "status": run.status,
        "cutoff": run.cutoff,
        "seed": run.seed,
        "time_mode": run.time_mode,
        "straddle_policy": run.straddle_policy,
        "subject_field": run.subject_field,
        "target_ratios": target_ratios,
        "buckets": run.summary.get("buckets", {}),
        "ratios": run.summary.get("ratios", {}),
        "warnings": run.summary.get("warnings", []),
        "leakage_statement": run.summary.get("leakage_statement", ""),
        "assignments": [
            {
                "sample_id": a.sample_id,
                "bucket": a.bucket,
                "root_subject": a.root_subject,
                "reason": a.reason,
            }
            for a in sorted(run.assignments, key=lambda x: x.sample_id)
        ],
        "conflicts": [
            {
                "subject": c.subject,
                "conflict_type": c.conflict_type,
                "severity": c.severity,
                "detail": c.detail,
                "sample_ids": c.sample_ids,
            }
            for c in run.conflicts
        ],
    }
