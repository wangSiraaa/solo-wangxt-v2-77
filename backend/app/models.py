"""ORM models: sample manifest, provenance links, split runs, assignments, conflicts."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# Bucket names a sample ends up in after a split.
BUCKET_TRAIN = "train"
BUCKET_EVAL = "eval"
BUCKET_EXCLUDED = "excluded"      # known subject, but violates the time rule
BUCKET_UNRESOLVED = "unresolved"  # missing / broken provenance — never split

ALL_BUCKETS = (BUCKET_TRAIN, BUCKET_EVAL, BUCKET_EXCLUDED, BUCKET_UNRESOLVED)


class Sample(Base):
    __tablename__ = "samples"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    captured_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    subject_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # Provenance: derived samples (crop / augment) point at the record they
    # came from. Chains are walked up to an *origin* sample at split time.
    parent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("samples.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), default="original")  # original|crop|augment
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    parent: Mapped["Sample | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["Sample"]] = relationship(back_populates="parent")


class SplitRun(Base):
    __tablename__ = "split_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cutoff: Mapped[date] = mapped_column(Date, nullable=False)
    subject_field: Mapped[str] = mapped_column(String(64), nullable=False)
    # {"__default__": 0.2, "cat": 0.3, ...} — desired eval share per category
    target_ratios: Mapped[dict] = mapped_column(JSON, default=dict)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    time_mode: Mapped[str] = mapped_column(String(32), default="hard")  # hard|grouped_stratify
    straddle_policy: Mapped[str] = mapped_column(String(32), default="train_lock")
    status: Mapped[str] = mapped_column(String(16), default="preview")  # preview|confirmed
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    assignments: Mapped[list["Assignment"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    conflicts: Mapped[list["Conflict"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class Assignment(Base):
    """Where every single sample belongs in one run."""

    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("split_runs.id", ondelete="CASCADE"), index=True)
    sample_id: Mapped[str] = mapped_column(String(64), index=True)
    bucket: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    root_subject: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[SplitRun] = relationship(back_populates="assignments")


class Conflict(Base):
    """Per-subject grouping problems surfaced for review (not auto-hidden)."""

    __tablename__ = "conflicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("split_runs.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(128), nullable=True)  # NULL for provenance errors
    conflict_type: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="warning")  # error|warning|info
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    sample_ids: Mapped[list] = mapped_column(JSON, default=list)

    run: Mapped[SplitRun] = relationship(back_populates="conflicts")
