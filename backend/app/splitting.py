"""Core splitting logic — provenance resolution, subject isolation and ratio audit.

Design notes
------------
* Identity is the **origin subject**: derived samples (crop/augment) walk the
  ``parent_id`` chain to the top and inherit that subject. Grouping is done on
  origin subjects only, so a subject can never land in both train and eval.
* Samples whose origin subject cannot be established are put in an
  ``unresolved`` bucket. They are *not* silently split and *not* claimed as
  "fixed" — the UI lists them and the response warns that their relation to the
  other sets is unknown.
* In ``hard`` time mode the cutoff decides membership: past-only groups go to
  train, future-only groups to eval, and groups straddling the cutoff are
  resolved with ``straddle_policy`` (samples on the forbidden side are
  ``excluded`` and the reason is recorded). Subject isolation is exact, but
  the achieved category ratios can deviate from the targets — that difference
  is reported rather than hidden.
* ``grouped_stratify`` additionally uses sklearn's StratifiedGroupKFold to
  chase the target ratios while keeping groups whole; groups straddling the
  cutoff are still flagged, because a random split ignores temporal order.
"""
from __future__ import annotations

import secrets
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

from .models import (
    BUCKET_EVAL,
    BUCKET_EXCLUDED,
    BUCKET_TRAIN,
    BUCKET_UNRESOLVED,
)

DEFAULT_EVAL_RATIO = 0.2
RATIO_TOLERANCE = 0.05  # |actual - target| beyond this generates a warning


@dataclass
class SplitParams:
    cutoff: date
    subject_field: str = "subject_id"
    target_ratios: dict[str, float] = field(
        default_factory=lambda: {"__default__": DEFAULT_EVAL_RATIO}
    )
    seed: int | None = None
    time_mode: str = "hard"
    straddle_policy: str = "train_lock"

    def target_for(self, label: str) -> float:
        if label in self.target_ratios:
            return self.target_ratios[label]
        return self.target_ratios.get("__default__", DEFAULT_EVAL_RATIO)


def normalize_targets(target: float | dict[str, float] | None) -> dict[str, float]:
    if target is None:
        return {"__default__": DEFAULT_EVAL_RATIO}
    if isinstance(target, (int, float)):
        return {"__default__": float(target)}
    out = dict(target)
    out.setdefault("__default__", DEFAULT_EVAL_RATIO)
    return out


def _resolve_provenance(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Walk parent chains. Returns (df with origin info, unresolved records).

    Columns added: root_subject, origin_id, issue (None when healthy).
    """
    by_id = df.set_index("sample_id").to_dict(orient="index")
    rows: list[dict] = []

    for sample_id, row in by_id.items():
        seen: list[str] = []
        cur_id, cur = sample_id, row
        issue: str | None = None

        parent_id = cur.get("parent_id")
        while parent_id is not None and not (
            isinstance(parent_id, float) and np.isnan(parent_id)
        ) and not pd.isna(parent_id):
            if parent_id in seen:
                issue = "provenance_cycle"
                break
            if parent_id not in by_id:
                issue = "dangling_parent"  # points at a record we do not have
                break
            seen.append(parent_id)
            cur_id, cur = parent_id, by_id[parent_id]
            parent_id = cur.get("parent_id")

        root_subject = cur.get("subject_id")
        if issue is None and (
            root_subject is None or (isinstance(root_subject, float) and np.isnan(root_subject))
        ):
            # The chain (if any) is intact, but the origin carries no identity.
            issue = "origin_without_subject"

        rows.append(
            {
                "sample_id": sample_id,
                "origin_id": cur_id,
                "root_subject": root_subject if not issue else None,
                "issue": issue,
            }
        )

    prov = pd.DataFrame(rows)
    out = df.merge(prov, on="sample_id", how="left")
    # JSON/SQL have no NaN: normalize pandas nulls to Python None.
    out = out.astype(object).where(pd.notna(out), None)
    unresolved = out[out["issue"].notna()].to_dict(orient="records")
    return out, unresolved


def _issue_reason(rec: dict) -> str:
    issue = rec["issue"]
    parent = rec.get("parent_id")
    has_parent = parent is not None and not pd.isna(parent)
    if issue == "dangling_parent":
        return (
            f"缺少可信来源：样本 {rec['sample_id']} 声称派生自 {parent}，"
            "但清单中不存在该父样本，无法确认其原始主体身份；已隔离，未参与拆分。"
        )
    if issue == "provenance_cycle":
        return (
            f"来源链成环：样本 {rec['sample_id']} 的派生关系形成循环，"
            "无法定位原始主体；已隔离，未参与拆分。"
        )
    if has_parent:
        return (
            f"原始主体缺失：样本 {rec['sample_id']} 的来源 {rec['origin_id']} "
            "没有主体标识，继承不到可信身份；已隔离，未参与拆分。"
        )
    return (
        f"缺少来源主体：样本 {rec['sample_id']} 没有主体标识"
        "（且不是可继承身份的派生样本）；已隔离，未参与拆分。"
    )


def _hard_assign(groups: pd.DataFrame, params: SplitParams) -> tuple[dict[str, str], dict[str, str], list[dict]]:
    """Strict temporal assignment. Returns (sample->bucket, sample->reason, conflicts)."""
    assignment: dict[str, str] = {}
    reasons: dict[str, str] = {}
    conflicts: list[dict] = []

    for subject, g in groups.groupby("root_subject", sort=True):
        ids = g["sample_id"].tolist()
        past = g[g["captured_at"] < params.cutoff]
        future = g[g["captured_at"] >= params.cutoff]

        if len(future) == 0:
            for sid in ids:
                assignment[sid] = BUCKET_TRAIN
        elif len(past) == 0:
            for sid in ids:
                assignment[sid] = BUCKET_EVAL
        else:
            # Straddles the cutoff: keep one subject in one side only.
            if params.straddle_policy == "train_lock":
                keep_side, drop_side, keep, drop = (
                    BUCKET_TRAIN,
                    BUCKET_EXCLUDED,
                    past,
                    future,
                )
                side_desc = "时间分界之后"
            else:
                keep_side, drop_side, keep, drop = (
                    BUCKET_EVAL,
                    BUCKET_EXCLUDED,
                    future,
                    past,
                )
                side_desc = "时间分界之前"
            for sid in keep["sample_id"]:
                assignment[sid] = keep_side
            for _, r in drop.iterrows():
                assignment[r["sample_id"]] = drop_side
                reasons[r["sample_id"]] = (
                    f"主体 {subject} 同时出现在时间分界两侧（{past['captured_at'].min()} ~ "
                    f"{future['captured_at'].max()}）；按 {params.straddle_policy} 策略整体保留在 "
                    f"{keep_side}，该{side_desc}样本被剔除，以免同一主体跨集合。"
                )
            conflicts.append(
                {
                    "subject": subject,
                    "conflict_type": "straddles_cutoff",
                    "severity": "warning",
                    "detail": (
                        f"主体 {subject} 的 {len(past)} 个样本早于 cutoff、{len(future)} 个不早于 cutoff，"
                        f"已按 {params.straddle_policy} 策略处理：{len(keep)} 个进入 {keep_side}，"
                        f"{len(drop)} 个被剔除。"
                    ),
                    "sample_ids": ids,
                }
            )
    return assignment, reasons, conflicts


def _stratified_assign(
    groups: pd.DataFrame, params: SplitParams
) -> tuple[dict[str, str], list[str], list[dict]]:
    """StratifiedGroupKFold split keeping subject groups whole."""
    rng = np.random.RandomState(params.seed)

    subject_rows = []
    for subject, g in groups.groupby("root_subject", sort=True):
        # Group label = majority category of its samples; ties broken by seed.
        counts = Counter(g["label"])
        top = max(counts.values())
        candidates = sorted(label for label, c in counts.items() if c == top)
        label = candidates[rng.randint(len(candidates))]
        subject_rows.append({"root_subject": subject, "grouplabel": label})

    sg = pd.DataFrame(subject_rows)
    k_groups = len(sg)
    min_class_groups = sg["grouplabel"].value_counts().min()
    max_splits = max(2, int(1 // min(params.target_ratios["__default__"], 0.5)))

    fallback_warning: str | None = None
    if k_groups < 2 or min_class_groups < 2:
        fallback_warning = (
            "可用主体组数不足（某些类别只有 1 个主体组），StratifiedGroupKFold 无法为该类别"
            "同时分配训练/评测；已回退到严格时间拆分，目标比例无法通过抽样满足。"
        )
    else:
        n_splits = min(max_splits, k_groups, int(min_class_groups))
        n_splits = max(n_splits, 2)
        best: tuple[float, dict[str, str]] | None = None

        for fold in range(n_splits):
            skf = StratifiedGroupKFold(
                n_splits=n_splits, shuffle=True, random_state=params.seed + fold
            )
            try:
                train_idx, eval_idx = next(
                    skf.split(
                        sg[["root_subject"]],
                        sg["grouplabel"],
                        groups=sg["root_subject"],
                    )
                )
            except ValueError as exc:  # pragma: no cover - defensive
                fallback_warning = f"分层分组拆分失败（{exc}），已回退到严格时间拆分。"
                break

            eval_subjects = set(sg.iloc[eval_idx]["root_subject"])
            candidate = {
                sid: (BUCKET_EVAL if s in eval_subjects else BUCKET_TRAIN)
                for sid, s in zip(groups["sample_id"], groups["root_subject"])
            }
            score = _ratio_penalty(groups, candidate, params)
            if best is None or score < best[0]:
                best = (score, candidate)

        if fallback_warning is None and best is not None:
            assignment = best[1]
            reasons: dict[str, str] = {}
            conflicts: list[dict] = []
            # Temporal audit: a grouped split is not ordered — flag straddlers.
            for subject, g in groups.groupby("root_subject", sort=True):
                if (g["captured_at"] < params.cutoff).any() and (
                    g["captured_at"] >= params.cutoff
                ).any():
                    bucket = assignment[g["sample_id"].iloc[0]]
                    conflicts.append(
                        {
                            "subject": subject,
                            "conflict_type": "straddles_cutoff",
                            "severity": "warning",
                            "detail": (
                                f"主体 {subject} 横跨时间分界两侧；grouped_stratify 为逼近目标比例"
                                f"将其整体放入 {bucket}，但这破坏了时间先后顺序，请确认是否接受。"
                            ),
                            "sample_ids": g["sample_id"].tolist(),
                        }
                    )
            return assignment, reasons, conflicts

    # Fallback: strict temporal split.
    assignment, reasons, conflicts = _hard_assign(groups, params)
    if fallback_warning:
        conflicts.append(
            {
                "subject": None,
                "conflict_type": "stratify_fallback",
                "severity": "warning",
                "detail": fallback_warning,
                "sample_ids": [],
            }
        )
    return assignment, reasons, conflicts


def _ratio_penalty(groups: pd.DataFrame, assignment: dict[str, str], params: SplitParams) -> float:
    labels = groups.assign(bucket=groups["sample_id"].map(assignment))
    pen = 0.0
    for label, g in labels.groupby("label"):
        n_eval = int((g["bucket"] == BUCKET_EVAL).sum())
        total = len(g)
        actual = n_eval / total if total else 0.0
        pen += abs(actual - params.target_for(label))
    return pen


def build_split(samples: list, params: SplitParams) -> dict:
    """Run the full pipeline. ``samples`` is an iterable of Sample ORM rows."""
    seed = params.seed if params.seed is not None else secrets.randbelow(2**32)
    params.seed = seed

    df = pd.DataFrame(
        [
            {
                "sample_id": s.id,
                "label": s.label,
                "captured_at": s.captured_at,
                "subject_id": s.subject_id,
                "parent_id": s.parent_id,
                "kind": s.kind,
            }
            for s in samples
        ]
    )

    warnings: list[str] = []
    conflicts: list[dict] = []
    assignment: dict[str, str] = {}
    reasons: dict[str, str] = {}

    if df.empty:
        return _package(df, assignment, reasons, conflicts, warnings, params, [])

    df, unresolved = _resolve_provenance(df)

    # Unresolved provenance → isolated, reported once per issue type.
    issue_groups: dict[str, list[dict]] = defaultdict(list)
    for rec in unresolved:
        assignment[rec["sample_id"]] = BUCKET_UNRESOLVED
        reasons[rec["sample_id"]] = _issue_reason(rec)
        issue_groups[rec["issue"]].append(rec)

    issue_labels = {
        "dangling_parent": "派生样本指向不存在的父样本",
        "provenance_cycle": "来源链成环",
        "origin_without_subject": "来源链顶端缺少主体标识",
    }
    for issue, recs in issue_groups.items():
        conflicts.append(
            {
                "subject": None,
                "conflict_type": f"unresolved_{issue}",
                "severity": "error",
                "detail": (
                    f"{issue_labels.get(issue, issue)}：{len(recs)} 个样本无法确认原始主体，"
                    "已放入 unresolved 桶，未进入 train/eval；这些样本与两个集合的关系未知，"
                    "不能据此声称泄漏已消除。"
                ),
                "sample_ids": [r["sample_id"] for r in recs],
            }
        )
        warnings.append(
            f"{len(recs)} 个样本缺少可信来源（{issue}），未参与拆分，需要人工补齐来源后重跑。"
        )

    resolved = df[df["issue"].isna()].copy()

    if not resolved.empty:
        if params.time_mode == "grouped_stratify":
            a, r, c = _stratified_assign(resolved, params)
        else:
            a, r, c = _hard_assign(resolved, params)
        assignment.update(a)
        reasons.update(r)
        conflicts.extend(c)

    return _package(df, assignment, reasons, conflicts, warnings, params, unresolved)


def _package(df, assignment, reasons, conflicts, warnings, params, unresolved) -> dict:
    all_ids = df["sample_id"].tolist() if not df.empty else []
    buckets = {BUCKET_TRAIN: 0, BUCKET_EVAL: 0, BUCKET_EXCLUDED: 0, BUCKET_UNRESOLVED: 0}
    for sid in all_ids:
        buckets[assignment.get(sid, BUCKET_UNRESOLVED)] += 1

    # Per-category ratio audit (train/eval only).
    ratios: dict[str, dict] = {}
    label_lookup = dict(zip(df["sample_id"], df["label"])) if not df.empty else {}
    labels = sorted(set(label_lookup.values()))
    for label in labels:
        ids = [sid for sid, lab in label_lookup.items() if lab == label]
        n_tr = sum(1 for sid in ids if assignment.get(sid) == BUCKET_TRAIN)
        n_ev = sum(1 for sid in ids if assignment.get(sid) == BUCKET_EVAL)
        n_un = sum(1 for sid in ids if assignment.get(sid) == BUCKET_UNRESOLVED)
        n_ex = sum(1 for sid in ids if assignment.get(sid) == BUCKET_EXCLUDED)
        total = n_tr + n_ev
        actual = (n_ev / total) if total else None
        target = params.target_for(label)
        diff = (actual - target) if actual is not None else None
        ratios[label] = {
            "target": target,
            "actual": actual,
            "diff": diff,
            "train": n_tr,
            "eval": n_ev,
            "excluded": n_ex,
            "unresolved": n_un,
        }
        if actual is None:
            warnings.append(
                f"类别「{label}」没有任何可拆分样本（unresolved={n_un}, excluded={n_ex}），"
                f"目标评测比例 {target:.0%} 无法达成。"
            )
            continue
        if n_ev == 0 and target > 0:
            warnings.append(
                f"罕见类别「{label}」可拆分样本全部落在训练侧（train={n_tr}），"
                f"评测集为 0，目标 {target:.0%} 无法达成，需要补充该时间窗内的独立主体。"
            )
        elif diff is not None and abs(diff) > RATIO_TOLERANCE:
            warnings.append(
                f"类别「{label}」实际评测比例 {actual:.1%} 与目标 {target:.0%} "
                f"相差 {diff:+.1%}（超过 {RATIO_TOLERANCE:.0%} 容忍度）。"
            )

    # Defensive isolation check — must never fire.
    sides: dict[str, set[str]] = defaultdict(set)
    for sid in all_ids:
        root = dict(zip(df["sample_id"], df["root_subject"])).get(sid) if not df.empty else None
        if root:
            sides[root].add(assignment.get(sid))
    crossed = {s: bs for s, bs in sides.items() if BUCKET_TRAIN in bs and BUCKET_EVAL in bs}
    if crossed:  # pragma: no cover - defensive guard
        conflicts.append(
            {
                "subject": None,
                "conflict_type": "isolation_violation",
                "severity": "error",
                "detail": f"主体隔离校验失败：{sorted(crossed)} 同时出现在 train 与 eval。",
                "sample_ids": [],
            }
        )

    if unresolved:
        leakage_statement = (
            "主体隔离在「来源已确认」的样本上成立：同一主体不会同时出现在 train 与 eval。"
            f"但有 {len(unresolved)} 个样本来源缺失/断裂（unresolved），其与两个集合的关系未知，"
            "因此不能宣称整体泄漏已经消除；请补齐来源后重新拆分。"
        )
    else:
        leakage_statement = (
            "全部样本的原始来源主体均已确认，同一主体只出现在一个集合中（excluded 样本不进入任何集合）。"
        )

    assignments_out = [
        {
            "sample_id": sid,
            "bucket": assignment.get(sid, BUCKET_UNRESOLVED),
            "root_subject": (
                dict(zip(df["sample_id"], df["root_subject"])).get(sid) if not df.empty else None
            ),
            "reason": reasons.get(sid),
        }
        for sid in all_ids
    ]

    return {
        "seed": params.seed,
        "buckets": buckets,
        "ratios": ratios,
        "warnings": warnings,
        "leakage_statement": leakage_statement,
        "assignments": assignments_out,
        "conflicts": conflicts,
    }
