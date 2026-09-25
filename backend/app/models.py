"""SQLAlchemy models: sample inventory, provenance links and saved split plans."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    subject_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Sample(Base):
    __tablename__ = "samples"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    sample_code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="original")
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    subject_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("subjects.id"), nullable=True
    )
    # Soft reference by sample code (no FK): dangling references to deleted /
    # external sources must be preserved so they can be flagged, not dropped.
    source_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    subject: Mapped[Subject | None] = relationship(lazy="joined")


class SplitPlan(Base):
    __tablename__ = "split_plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="preview")
    cutoff_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    subject_field: Mapped[str] = mapped_column(String(64), nullable=False, default="subject_id")
    target_eval_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    target_label_ratios: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    cutoff_policy: Mapped[str] = mapped_column(String(32), nullable=False, default="exclude")
    stats: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SplitAssignment(Base):
    __tablename__ = "split_assignments"
    __table_args__ = (UniqueConstraint("plan_id", "sample_id", name="uq_plan_sample"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    plan_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("split_plans.id", ondelete="CASCADE"), nullable=False
    )
    sample_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("samples.id"), nullable=False
    )
    effective_subject_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assignment: Mapped[str] = mapped_column(String(16), nullable=False)  # train/eval/excluded
    reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    inherited: Mapped[bool] = mapped_column(Boolean, default=False)

    plan: Mapped[SplitPlan] = relationship()
    sample: Mapped[Sample] = relationship(lazy="joined")
