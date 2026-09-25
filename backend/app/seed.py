"""Deterministic demo inventory used to validate subject isolation and the
time-cutoff condition.

Scenario coverage:
* S-101 / S-102: subjects photographed in BOTH 2024-05 and 2024-07
  (cutoff-crossing -> default quarantined).
* S-103..S-107: subjects seen only before the cutoff (split candidates).
* S-108:     subject seen only after the cutoff (forced to eval).
* S-109:     sole carrier of rare label "rare-anomaly".
* DERIVED-1: valid crop, inherits S-103's identity.
* DERIVED-2: augmented crop that references a deleted/unknown source
  -> cannot establish origin -> quarantined, reported, NOT certified safe.
* DERIVED-3 / DERIVED-4: source chain cycle -> quarantined.
* S-110:     original sample without any subject identity.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .models import Sample, SplitAssignment, SplitPlan, Subject

DEMO_SAMPLES = [
    # (code, kind, label, collected_at, subject, source_ref)
    ("IMG-001", "original", "cat", "2024-05-10T09:00:00", "S-101", None),
    ("IMG-002", "original", "cat", "2024-07-15T09:00:00", "S-101", None),
    ("IMG-003", "original", "dog", "2024-05-20T09:00:00", "S-102", None),
    ("IMG-004", "original", "dog", "2024-07-02T09:00:00", "S-102", None),

    ("IMG-005", "original", "cat", "2024-04-01T09:00:00", "S-103", None),
    ("IMG-006", "original", "cat", "2024-03-11T09:00:00", "S-104", None),
    ("IMG-007", "original", "dog", "2024-02-18T09:00:00", "S-105", None),
    ("IMG-008", "original", "dog", "2024-05-30T09:00:00", "S-106", None),
    ("IMG-009", "original", "cat", "2024-01-05T09:00:00", "S-107", None),

    ("IMG-010", "original", "bird", "2024-08-01T09:00:00", "S-108", None),
    ("IMG-011", "original", "rare-anomaly", "2024-04-22T09:00:00", "S-109", None),
    ("IMG-012", "original", "bird", "2024-05-01T09:00:00", None, None),

    # Valid derived sample: crop of IMG-005 inherits subject S-103.
    ("CROP-001", "crop", "cat", "2024-04-02T10:00:00", None, "IMG-005"),

    # Derived sample whose origin was deleted / never registered.
    ("CROP-002", "augment", "cat", "2024-04-03T10:00:00", None, "IMG-GONE-999"),

    # Two-node source cycle: impossible provenance.
    ("CROP-003", "augment", "dog", "2024-03-01T10:00:00", None, "CROP-004"),
    ("CROP-004", "crop", "dog", "2024-03-01T10:05:00", None, "CROP-003"),
]


def reset_demo(db: Session) -> dict:
    db.execute(delete(SplitAssignment))
    db.execute(delete(SplitPlan))
    db.execute(delete(Sample))
    db.execute(delete(Subject))

    subjects: dict[str, Subject] = {}
    created_samples: dict[str, Sample] = {}
    for code, kind, label, ts, subject_key, _src in DEMO_SAMPLES:
        if subject_key and subject_key not in subjects:
            subj = Subject(subject_key=subject_key, display_name=f"主体 {subject_key}")
            db.add(subj)
            db.flush()
            subjects[subject_key] = subj
        sample = Sample(
            sample_code=code,
            kind=kind,
            label=label,
            collected_at=datetime.fromisoformat(ts),
            subject_id=subjects[subject_key].id if subject_key else None,
        )
        db.add(sample)
        db.flush()
        created_samples[code] = sample

    # Second pass: wire source references (includes dangling + cyclic ones).
    for code, _kind, _label, _ts, _subject, src in DEMO_SAMPLES:
        if src:
            created_samples[code].source_ref = src

    db.commit()
    return {"loaded_samples": len(DEMO_SAMPLES), "subjects": len(subjects)}
