"""Algorithm-level validation of the required scenarios."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from app.splitter import SplitParams, build_split


def _demo_df() -> pd.DataFrame:
    from app.seed import DEMO_SAMPLES

    df = pd.DataFrame(
        DEMO_SAMPLES,
        columns=[
            "sample_code",
            "kind",
            "label",
            "collected_at",
            "subject_key",
            "source_sample_code",
        ],
    )
    df["collected_at"] = pd.to_datetime(df["collected_at"])
    return df


def by_code(result):
    return {a["sample_code"]: a for a in result["assignments"]}


def test_subject_isolation_when_subject_spans_months():
    """S-101 / S-102 appear in May and July and must be fully quarantined."""
    res = build_split(
        _demo_df(),
        SplitParams(cutoff_date=datetime(2024, 6, 1), target_eval_ratio=0.3, seed=42),
    )
    a = by_code(res)
    for code in ("IMG-001", "IMG-002", "IMG-003", "IMG-004"):
        assert a[code]["assignment"] == "excluded"
        assert "cutoff_crossing" in a[code]["reasons"]

    # No subject key appears on both train and eval sides.
    sides = {}
    for item in res["assignments"]:
        if item["assignment"] in ("train", "eval") and item["effective_subject_key"]:
            sides.setdefault(item["effective_subject_key"], set()).add(
                item["assignment"]
            )
    assert all(len(v) == 1 for v in sides.values())
    assert res["stats"]["assertions"]["subject_isolation"] is True


def test_derived_sample_inherits_origin_identity():
    res = build_split(
        _demo_df(),
        SplitParams(cutoff_date=datetime(2024, 6, 1), target_eval_ratio=0.3, seed=42),
    )
    a = by_code(res)
    crop = a["CROP-001"]
    assert crop["effective_subject_key"] == "S-103"
    assert crop["inherited"] is True
    assert "inherited_identity" in crop["reasons"]
    # Inherits the exact side of its origin subject IMG-005.
    assert crop["assignment"] == a["IMG-005"]["assignment"]


def test_derived_sample_missing_source_is_quarantined_not_certified():
    res = build_split(
        _demo_df(),
        SplitParams(cutoff_date=datetime(2024, 6, 1), target_eval_ratio=0.3, seed=42),
    )
    a = by_code(res)
    assert a["CROP-002"]["assignment"] == "excluded"
    assert "missing_source_ref" in a["CROP-002"]["reasons"]
    assert res["stats"]["unresolved_relationships"] >= 1
    # Every unresolved sample is in quarantine ...
    assert res["stats"]["assertions"]["unknown_provenance_quarantined"] is True

    # ... and source cycles are treated identically (no guessed identity).
    for code in ("CROP-003", "CROP-004"):
        assert a[code]["assignment"] == "excluded"
        assert "source_cycle" in a[code]["reasons"]

    # Original sample without subject identity is quarantined separately.
    assert a["IMG-012"]["assignment"] == "excluded"
    assert "missing_subject" in a["IMG-012"]["reasons"]


def test_time_condition_train_is_strictly_pre_cutoff():
    res = build_split(
        _demo_df(),
        SplitParams(cutoff_date=datetime(2024, 6, 1), target_eval_ratio=0.3, seed=42),
    )
    assert res["stats"]["time_condition"]["train_samples_after_cutoff"] == 0
    assert res["stats"]["assertions"]["train_before_cutoff_only"] is True
    a = by_code(res)
    assert a["IMG-010"]["assignment"] == "eval"
    assert "post_cutoff_group" in a["IMG-010"]["reasons"]


def test_ratio_deviation_is_reported_for_rare_label():
    res = build_split(
        _demo_df(),
        SplitParams(cutoff_date=datetime(2024, 6, 1), target_eval_ratio=0.3, seed=42),
    )
    rare = res["stats"]["per_label"]["rare-anomaly"]
    # Single carrier subject cannot be split: deviation is reported honestly.
    assert rare["total"] == 1
    assert rare["diff"] in (-0.3, 0.7)
    assert any(
        n.startswith("rare_single_group_labels") for n in res["stats"]["notes"]
    )
    assert isinstance(res["stats"]["ratio_diff"], float)


def test_seed_makes_split_reproducible():
    params = dict(
        cutoff_date=datetime(2024, 6, 1), target_eval_ratio=0.3, seed=7
    )
    r1 = build_split(_demo_df(), SplitParams(**params))
    r2 = build_split(_demo_df(), SplitParams(**params))
    assert [
        (a["sample_code"], a["assignment"]) for a in r1["assignments"]
    ] == [(a["sample_code"], a["assignment"]) for a in r2["assignments"]]


def test_unsafe_cutoff_policy_reports_violation_instead_of_hiding_it():
    res = build_split(
        _demo_df(),
        SplitParams(
            cutoff_date=datetime(2024, 6, 1),
            target_eval_ratio=0.3,
            seed=42,
            cutoff_policy="train",
        ),
    )
    a = by_code(res)
    assert a["IMG-002"]["assignment"] == "train"
    assert "train_after_cutoff_violation" in a["IMG-002"]["reasons"]
    # The hard temporal guarantee is now FALSE, and it is reported as such.
    assert res["stats"]["assertions"]["train_before_cutoff_only"] is False
    assert res["stats"]["time_condition"]["train_samples_after_cutoff"] > 0
    # Unknown provenance is still never called safe.
    assert a["CROP-002"]["assignment"] == "excluded"


def test_invalid_params_rejected():
    with pytest.raises(ValueError):
        SplitParams(
            cutoff_date=datetime(2024, 6, 1),
            target_eval_ratio=1.5,
            seed=1,
        )
