"""End-to-end verification of the scenarios called out in the task:

  A. subject spanning across months (time boundary) stays isolated
  B. rare category whose target ratio is unreachable -> reported, not faked
  C. derived sample missing provenance -> isolated; leakage not claimed fixed

Runs entirely in-process against a temporary SQLite database (no server
needed):  python verify_demo.py
"""
from __future__ import annotations

import os
import tempfile
from datetime import date

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"

from app import crud  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.schemas import SampleIn, SplitRequest  # noqa: E402

PASS, FAIL = "✅ 通过", "❌ 失败"


def add(db, sid, label, captured, subject=None, parent=None, kind="original"):
    crud.upsert_sample(
        db,
        SampleIn(
            id=sid, label=label, captured_at=captured,
            subject_id=subject, parent_id=parent, kind=kind,
        ),
    )


def main() -> int:
    init_db()
    db = SessionLocal()
    results: list[tuple[str, bool, str]] = []

    # --- demo corpus -------------------------------------------------------
    # subj-A: July (train side) AND August (eval side) — crosses months
    add(db, "a1", "normal", date(2026, 7, 10), "subj-A")
    add(db, "a2", "normal", date(2026, 8, 5), "subj-A")
    add(db, "a2-crop", "normal", date(2026, 8, 5), None, parent="a2", kind="crop")
    # subj-B: past only
    add(db, "b1", "normal", date(2026, 7, 1), "subj-B")
    # subj-C: future only
    add(db, "c1", "normal", date(2026, 8, 20), "subj-C")
    # rare class: single subject, past side only -> eval target unreachable
    add(db, "d1", "rare_anomaly", date(2026, 7, 15), "subj-D")
    # derived sample whose parent is absent from the manifest
    add(db, "x-crop", "normal", date(2026, 7, 18), None, parent="ghost-origin", kind="crop")
    db.commit()

    req = SplitRequest(
        cutoff=date(2026, 8, 1),
        subject_field="subject_id",
        target_eval_ratio={"__default__": 0.34, "rare_anomaly": 0.5},
        seed=42,
        time_mode="hard",
        straddle_policy="train_lock",
    )
    _, res = crud.run_split(db, req)
    db.commit()
    b = {a["sample_id"]: a["bucket"] for a in res["assignments"]}
    roots = {a["sample_id"]: a["root_subject"] for a in res["assignments"]}

    # --- A. cross-month subject isolation ---------------------------------
    sides: dict[str, set[str]] = {}
    for a in res["assignments"]:
        if a["root_subject"]:
            sides.setdefault(a["root_subject"], set()).add(a["bucket"])
    no_cross = not ({"train", "eval"} <= sides.get("subj-A", set()))
    results.append((
        "A1 跨月份主体 subj-A 没有同时进入 train/eval",
        no_cross,
        f"subj-A 所在桶={sorted(sides.get('subj-A', set()))}",
    ))
    results.append((
        "A2 train_lock 下边界后样本被剔除（而不是泄漏进评测集）",
        b["a2"] == "excluded",
        f"a2={b['a2']}",
    ))
    results.append((
        "A3 裁切样本继承原始来源主体 subj-A 并随主体一致处理",
        roots["a2-crop"] == "subj-A" and b["a2-crop"] == b["a2"],
        f"a2-crop root={roots['a2-crop']}, bucket={b['a2-crop']}",
    ))
    results.append((
        "A4 时间条件成立：纯历史→train，纯未来→eval",
        b["b1"] == "train" and b["c1"] == "eval",
        f"b1={b['b1']}, c1={b['c1']}",
    ))

    # --- B. rare category --------------------------------------------------
    rare = res["ratios"]["rare_anomaly"]
    results.append((
        "B1 罕见类别实际比例与目标的差异被如实报告（eval=0，目标 50% 无法达成）",
        rare["eval"] == 0 and rare["train"] == 1 and rare["actual"] == 0.0,
        f"target={rare['target']:.0%}, actual={rare['actual']:.0%}, diff={rare['diff']:+.0%}",
    ))
    results.append((
        "B2 针对不可达目标给出显式告警，而不是强行制造评测样本",
        any("无法达成" in w for w in res["warnings"]),
        f"warnings={len(res['warnings'])} 条",
    ))

    # --- C. missing provenance --------------------------------------------
    results.append((
        "C1 缺来源的派生样本进入 unresolved 桶，未参与 train/eval",
        b["x-crop"] == "unresolved",
        f"x-crop={b['x-crop']}",
    ))
    results.append((
        "C2 unresolved 以 error 级别冲突单独提示",
        any(
            c["conflict_type"] == "unresolved_dangling_parent" and c["severity"] == "error"
            for c in res["conflicts"]
        ),
        "conflicts=" + ", ".join(sorted({c["conflict_type"] for c in res["conflicts"]})),
    ))
    results.append((
        "C3 不把未知关系说成泄漏已消除",
        "未知" in res["leakage_statement"] and "不能宣称" in res["leakage_statement"],
        res["leakage_statement"],
    ))

    # --- persisted run -----------------------------------------------------
    from app.models import SplitRun

    orm_run = db.get(SplitRun, res["run_id"])
    saved = crud.serialize_run(orm_run)
    results.append((
        "D1 预览已保存清单与种子，可随时回查",
        saved["status"] == "preview" and saved["seed"] == 42 and len(saved["assignments"]) == 7,
        f"run_id={saved['run_id']}, seed={saved['seed']}, assignments={len(saved['assignments'])}",
    ))
    crud.confirm_run(db, orm_run)
    db.commit()
    confirmed = crud.serialize_run(db.get(SplitRun, res["run_id"]))
    results.append((
        "D2 确认后状态变为 confirmed，归属与原因仍可逐条查看",
        confirmed["status"] == "confirmed"
        and all(a["bucket"] for a in confirmed["assignments"]),
        f"status={confirmed['status']}",
    ))
    db.close()

    name = "主体跨月份 / 罕见类别 / 派生样本缺来源 验证"
    print(f"\n{'=' * 78}\n{name}\n{'=' * 78}")
    ok_all = True
    for title, ok, detail in results:
        ok_all &= ok
        print(f"[{PASS if ok else FAIL}] {title}\n      └ {detail}")
    print("=" * 78)
    print("泄漏结论原文：")
    print("  " + res["leakage_statement"])
    print("=" * 78)
    print("总体：", "全部通过 ✅" if ok_all else "存在失败项 ❌")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
