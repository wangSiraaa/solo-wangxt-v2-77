"""Pydantic request/response schemas."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SampleIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    captured_at: date
    subject_id: str | None = None
    parent_id: str | None = None
    kind: Literal["original", "crop", "augment"] = "original"


class SampleOut(SampleIn):
    created_at: datetime

    class Config:
        from_attributes = True


class SplitRequest(BaseModel):
    cutoff: date
    subject_field: str = "subject_id"
    # Desired *eval* share. A scalar applies to every category; a dict allows
    # per-category overrides, key "__default__" sets the global default.
    target_eval_ratio: float | dict[str, float] | None = None
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    time_mode: Literal["hard", "grouped_stratify"] = "hard"
    straddle_policy: Literal["train_lock", "eval_lock"] = "train_lock"

    @field_validator("subject_field")
    @classmethod
    def _subject_field_allowed(cls, v: str) -> str:
        from .config import settings

        if v not in settings.allowed_subject_fields:
            raise ValueError(
                f"subject_field must be one of {settings.allowed_subject_fields}"
            )
        return v


class RatioStat(BaseModel):
    target: float | None
    actual: float | None  # None when the class has no splittable samples at all
    diff: float | None
    train: int
    eval: int
    excluded: int = 0
    unresolved: int = 0


class AssignmentOut(BaseModel):
    sample_id: str
    bucket: str
    root_subject: str | None
    reason: str | None

    class Config:
        from_attributes = True


class ConflictOut(BaseModel):
    subject: str | None
    conflict_type: str
    severity: str
    detail: str
    sample_ids: list[str]

    class Config:
        from_attributes = True


class SplitResult(BaseModel):
    run_id: int
    status: str
    cutoff: date
    seed: int
    time_mode: str
    straddle_policy: str
    subject_field: str
    target_ratios: dict[str, float]
    buckets: dict[str, int]
    ratios: dict[str, RatioStat]
    warnings: list[str]
    leakage_statement: str
    assignments: list[AssignmentOut]
    conflicts: list[ConflictOut]
