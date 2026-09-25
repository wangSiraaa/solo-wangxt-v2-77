import os
import tempfile

import pytest

# Point the app at a throwaway SQLite file before any app module imports config.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Sample  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.seed_demo import DEMO_SAMPLES  # noqa: E402


@pytest.fixture()
def client():
    init_db()
    db = SessionLocal()
    db.query(Sample).delete()
    db.commit()
    db.close()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def demo_client(client):
    rows = [
        {
            "id": sid,
            "label": label,
            "captured_at": captured.isoformat(),
            "subject_id": subject,
            "parent_id": parent,
            "kind": kind,
        }
        for sid, label, captured, subject, parent, kind in DEMO_SAMPLES
    ]
    r = client.post("/api/samples/bulk", json=rows)
    assert r.status_code == 201, r.text
    return client


PREVIEW_BODY = {
    "cutoff": "2026-08-01",
    "subject_field": "subject_id",
    "target_eval_ratio": {"__default__": 0.2, "rare_anomaly": 0.5},
    "seed": 42,
    "time_mode": "hard",
    "straddle_policy": "train_lock",
}


def buckets_by_sample(result):
    return {a["sample_id"]: a["bucket"] for a in result["assignments"]}


def subject_sides(result):
    sides = {}
    for a in result["assignments"]:
        if a["root_subject"]:
            sides.setdefault(a["root_subject"], set()).add(a["bucket"])
    return sides


def test_demo_seed_loaded(demo_client):
    r = demo_client.get("/api/samples")
    assert r.status_code == 200
    assert len(r.json()) == len(DEMO_SAMPLES)


def test_subject_isolation_across_months(demo_client):
    r = demo_client.post("/api/splits/preview", json=PREVIEW_BODY)
    assert r.status_code == 200, r.text
    result = r.json()
    b = buckets_by_sample(result)

    # subj-001 spans June -> August; train_lock keeps past samples in train
    # and removes the future ones instead of leaking them into eval.
    assert b["s001"] == "train" and b["s002"] == "train"
    assert b["s003"] == "excluded"

    # Derived samples inherit the ORIGIN subject across a two-hop chain.
    roots = {a["sample_id"]: a["root_subject"] for a in result["assignments"]}
    assert roots["s004"] == "subj-001"   # crop of s003
    assert roots["s005"] == "subj-001"   # augment of the crop
    assert b["s004"] == "excluded" and b["s005"] == "excluded"
    assert roots["s008"] == "subj-002"

    # Hard guarantee: no subject appears in both train and eval.
    for subject, bs in subject_sides(result).items():
        assert not ({"train", "eval"} <= bs), f"{subject} leaked: {bs}"

    # Past-only / future-only groups follow the time boundary.
    assert b["s009"] == "train" and b["s010"] == "train"
    assert b["s013"] == "train"
    assert b["s014"] == "eval"

    # Straddle conflicts are recorded with reasons.
    kinds = {c["conflict_type"] for c in result["conflicts"]}
    assert "straddles_cutoff" in kinds
    straddlers = {c["subject"] for c in result["conflicts"] if c["conflict_type"] == "straddles_cutoff"}
    assert {"subj-001", "subj-002", "subj-004"} <= straddlers

    excluded_reasons = [a for a in result["assignments"] if a["bucket"] == "excluded"]
    assert all(a["reason"] for a in excluded_reasons)


def test_rare_class_target_unreachable_is_reported_not_hidden(demo_client):
    r = demo_client.post("/api/splits/preview", json=PREVIEW_BODY)
    result = r.json()
    rare = result["ratios"]["rare_anomaly"]

    # subj-004's future sample was excluded by train_lock and subj-005 has no
    # future sample: eval=0 for the rare class, target 50% cannot be met.
    assert rare["eval"] == 0
    assert rare["train"] >= 1
    assert any("rare_anomaly" in w or "罕见" in w for w in result["warnings"])
    assert any("无法达成" in w for w in result["warnings"])

    # normal class: only the future-only subject lands in eval.
    normal = result["ratios"]["normal"]
    assert normal["eval"] == 1  # s014
    assert normal["actual"] != normal["target"]  # deviation reported


def test_derived_sample_with_missing_provenance_is_isolated(demo_client):
    r = demo_client.post("/api/splits/preview", json=PREVIEW_BODY)
    result = r.json()
    b = buckets_by_sample(result)

    # The crop pointing at a non-existent parent is unresolved, never split.
    assert b["s015"] == "unresolved"
    s015 = next(a for a in result["assignments"] if a["sample_id"] == "s015")
    assert s015["root_subject"] is None
    assert "无法确认" in s015["reason"]

    # Error-level conflict and a warning that asks for manual provenance.
    unresolved_conflicts = [c for c in result["conflicts"] if c["conflict_type"] == "unresolved_dangling_parent"]
    assert unresolved_conflicts and unresolved_conflicts[0]["severity"] == "error"
    assert any("缺少可信来源" in w for w in result["warnings"])

    # Crucial wording: unknown relationships must not be called eliminated.
    assert "不能宣称" in result["leakage_statement"] or "未知" in result["leakage_statement"]
    assert result["buckets"]["unresolved"] == 1


def test_eval_lock_policy_moves_straddlers_to_eval(demo_client):
    body = {**PREVIEW_BODY, "straddle_policy": "eval_lock"}
    r = demo_client.post("/api/splits/preview", json=body)
    result = r.json()
    b = buckets_by_sample(result)

    # Future side kept (eval), past side excluded.
    assert b["s003"] == b["s004"] == b["s005"] == "eval"
    assert b["s001"] == b["s002"] == "excluded"
    assert b["s012"] == "eval" and b["s011"] == "excluded"

    # Still isolated.
    for subject, bs in subject_sides(result).items():
        assert not ({"train", "eval"} <= bs)


def test_grouped_stratify_keeps_groups_whole_and_flags_time_violation(demo_client):
    body = {**PREVIEW_BODY, "time_mode": "grouped_stratify"}
    r = demo_client.post("/api/splits/preview", json=body)
    assert r.status_code == 200, r.text
    result = r.json()

    # No subject in both sets even when ratios are chased via StratifiedGroupKFold.
    for subject, bs in subject_sides(result).items():
        assert not ({"train", "eval"} <= bs)

    # Groups straddling the cutoff are flagged because the random order
    # ignores temporal sequencing.
    straddlers = {c["subject"] for c in result["conflicts"] if c["conflict_type"] == "straddles_cutoff"}
    assert {"subj-001", "subj-002", "subj-004"} <= straddlers
    assert buckets_by_sample(result)["s015"] == "unresolved"


def test_seed_is_reproducible_and_persisted(demo_client):
    r1 = demo_client.post("/api/splits/preview", json={**PREVIEW_BODY, "time_mode": "grouped_stratify"})
    r2 = demo_client.post("/api/splits/preview", json={**PREVIEW_BODY, "time_mode": "grouped_stratify"})
    a1 = sorted((a["sample_id"], a["bucket"]) for a in r1.json()["assignments"])
    a2 = sorted((a["sample_id"], a["bucket"]) for a in r2.json()["assignments"])
    assert a1 == a2
    assert r1.json()["seed"] == r2.json()["seed"] == 42


def test_confirm_persists_manifest_and_is_idempotent_block(demo_client):
    r = demo_client.post("/api/splits/preview", json=PREVIEW_BODY)
    run_id = r.json()["run_id"]

    r = demo_client.post(f"/api/splits/{run_id}/confirm")
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"
    assert len(r.json()["assignments"]) == len(DEMO_SAMPLES)

    # Second confirmation is rejected.
    r2 = demo_client.post(f"/api/splits/{run_id}/confirm")
    assert r2.status_code == 409

    # Stored run is retrievable later.
    r3 = demo_client.get(f"/api/splits/{run_id}")
    assert r3.status_code == 200
    assert r3.json()["seed"] == 42


def test_origin_without_subject_and_cycle(demo_client):
    extra = [
        {"id": "s100", "label": "normal", "captured_at": "2026-07-01",
         "subject_id": None, "parent_id": None, "kind": "original"},
        {"id": "s101", "label": "normal", "captured_at": "2026-07-02",
         "subject_id": None, "parent_id": "s100", "kind": "crop"},
    ]
    assert demo_client.post("/api/samples/bulk", json=extra).status_code == 201
    r = demo_client.post("/api/splits/preview", json=PREVIEW_BODY)
    b = buckets_by_sample(r.json())
    assert b["s100"] == "unresolved" and b["s101"] == "unresolved"
