"""End-to-end API tests through FastAPI + PostgreSQL."""
from __future__ import annotations


PREVIEW_BODY = {
    "cutoff_date": "2024-06-01",
    "target_eval_ratio": 0.3,
    "seed": 42,
    "cutoff_policy": "exclude",
    "name": "demo-preview",
}


def test_demo_reset_lists_samples(client):
    r = client.post("/api/demo/reset")
    assert r.status_code == 200
    assert r.json()["loaded_samples"] == 16

    r = client.get("/api/samples")
    samples = r.json()
    assert len(samples) == 16
    crop = next(s for s in samples if s["sample_code"] == "CROP-001")
    assert crop["source_sample_code"] == "IMG-005"
    dangling = next(s for s in samples if s["sample_code"] == "CROP-002")
    assert dangling["source_sample_code"] == "IMG-GONE-999"


def test_preview_confirms_and_persists_seed(client):
    client.post("/api/demo/reset")
    r = client.post("/api/splits/preview", json=PREVIEW_BODY)
    assert r.status_code == 200, r.text
    body = r.json()
    plan_id = body["plan_id"]

    stats = body["stats"]
    assert stats["assertions"]["subject_isolation"] is True
    assert stats["time_condition"]["train_samples_after_cutoff"] == 0
    assert stats["unresolved_relationships"] == 4  # dangling + cycle x2 + no-subject
    assert body["params"]["seed"] == 42

    # Confirmation persists the plan (inventory + seed) and is repeatable read.
    r2 = client.post("/api/splits/confirm", json={"plan_id": plan_id})
    assert r2.status_code == 200
    assert r2.json()["status"] == "confirmed"
    assert r2.json()["seed"] == 42

    r3 = client.get(f"/api/splits/{plan_id}")
    detail = r3.json()
    assert len(detail["assignments"]) == 16
    dangling = next(
        a for a in detail["assignments"] if a["sample_code"] == "CROP-002"
    )
    assert dangling["assignment"] == "excluded"
    assert "missing_source_ref" in dangling["reasons"]

    # Double confirm is rejected.
    r4 = client.post("/api/splits/confirm", json={"plan_id": plan_id})
    assert r4.status_code == 409


def test_each_sample_view_has_assignment_and_reasons(client):
    client.post("/api/demo/reset")
    body = client.post("/api/splits/preview", json=PREVIEW_BODY).json()
    for a in body["assignments"]:
        assert a["assignment"] in ("train", "eval", "excluded")
        assert isinstance(a["reasons"], list)
        assert "effective_subject_key" in a


def test_force_eval_policy_is_marked_unsafe(client):
    client.post("/api/demo/reset")
    body = PREVIEW_BODY | {"cutoff_policy": "eval"}
    r = client.post("/api/splits/preview", json=body).json()
    assert r["stats"]["time_condition"]["forced_pre_cutoff_samples_in_eval"] > 0


def test_invalid_ratio_returns_422(client):
    client.post("/api/demo/reset")
    r = client.post(
        "/api/splits/preview",
        json=PREVIEW_BODY | {"target_eval_ratio": 1.2},
    )
    assert r.status_code == 422
