"""Seed the demo dataset described in the task:

* subjects spanning across the time boundary (subj-001, subj-002, subj-004)
* a rare category (rare_anomaly) with no future samples -> target unreachable
* derived samples (crop / augment) inheriting origin identity across months
* a derived sample whose provenance is missing -> isolated, reported, not split

Run:  python -m app.seed_demo
"""
from datetime import date

from sqlalchemy import select

from .database import SessionLocal, init_db
from .models import Sample

CUTOFF = date(2026, 8, 1)

DEMO_SAMPLES = [
    # subj-001: straddles the cutoff (June train side + August eval side)
    ("s001", "normal", date(2026, 6, 5), "subj-001", None, "original"),
    ("s002", "normal", date(2026, 7, 20), "subj-001", None, "original"),
    ("s003", "normal", date(2026, 8, 3), "subj-001", None, "original"),
    # crop of s003 -> inherits subj-001, even if its own subject_id were blank
    ("s004", "normal", date(2026, 8, 3), None, "s003", "crop"),
    # augment of the crop (two-hop chain) still inherits subj-001
    ("s005", "normal", date(2026, 8, 4), None, "s004", "augment"),

    # subj-002: another straddler
    ("s006", "normal", date(2026, 7, 10), "subj-002", None, "original"),
    ("s007", "normal", date(2026, 8, 12), "subj-002", None, "original"),
    ("s008", "normal", date(2026, 7, 11), None, "s006", "augment"),

    # subj-003: past only -> train
    ("s009", "normal", date(2026, 6, 28), "subj-003", None, "original"),
    ("s010", "normal", date(2026, 7, 2), None, "s009", "crop"),

    # subj-004: rare anomaly, straddles cutoff
    ("s011", "rare_anomaly", date(2026, 7, 25), "subj-004", None, "original"),
    ("s012", "rare_anomaly", date(2026, 8, 6), "subj-004", None, "original"),

    # subj-005: rare anomaly past only -> no eval possible for the rare class
    ("s013", "rare_anomaly", date(2026, 6, 15), "subj-005", None, "original"),

    # subj-006: future only -> eval
    ("s014", "normal", date(2026, 8, 20), "subj-006", None, "original"),

    # DERIVED SAMPLE MISSING PROVENANCE: claims crop ancestry but the parent
    # record was deleted/never imported -> cannot establish origin subject.
    ("s015", "normal", date(2026, 7, 18), None, "s999-missing", "crop"),
]


def seed() -> int:
    init_db()
    db = SessionLocal()
    try:
        existing = {row[0] for row in db.execute(select(Sample.id)).all()}
        n = 0
        for sid, label, captured, subject, parent, kind in DEMO_SAMPLES:
            if sid in existing:
                continue
            db.add(
                Sample(
                    id=sid,
                    label=label,
                    captured_at=captured,
                    subject_id=subject,
                    parent_id=parent,
                    kind=kind,
                )
            )
            n += 1
        db.commit()
        return n
    finally:
        db.close()


if __name__ == "__main__":
    added = seed()
    print(f"seeded {added} demo samples (cutoff for demo: {CUTOFF})")
