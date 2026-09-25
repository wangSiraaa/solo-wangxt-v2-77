"""Pydantic request/response models."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class SubjectIn(BaseModel):
    subject_key: str = Field(min_length=1, max_length=255)
    display_name: Optional[str] = None


class SampleIn(BaseModel):
    sample_code: str = Field(min_length=1, max_length=128)
    kind: Literal["original", "crop", "augment"] = "original"
    label: str = Field(min_length=1, max_length=128)
    collected_at: datetime
    subject_key: Optional[str] = None
    source_sample_code: Optional[str] = None
    note: Optional[str] = None


class SampleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sample_code: str
    kind: str
    label: str
    collected_at: datetime
    note: Optional[str] = None


class SplitRequest(BaseModel):
    cutoff_date: date
    target_eval_ratio: float = Field(ge=0.0, le=1.0)
    seed: int = Field(ge=0, le=2_147_483_647)
    cutoff_policy: Literal["exclude", "eval", "train"] = "exclude"
    target_label_ratios: dict[str, float] = Field(default_factory=dict)
    subject_field: Literal["subject_id"] = "subject_id"
    name: str = Field(default="plan", max_length=255)


class ConfirmRequest(BaseModel):
    plan_id: str
