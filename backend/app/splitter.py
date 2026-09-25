"""Subject-aware temporal train/eval split planner (pandas + scikit-learn).

Guarantees and honest limitations:

* A subject whose identity is known is assigned to exactly one side
  (train / eval) or quarantined. No subject appears in both train and eval.
* Derived samples (crop / augmentation) inherit the *origin* subject by
  walking the source chain to its original sample.
* Samples whose origin cannot be established (unknown source id, source cycle,
  no subject) are quarantined and reported. They are NOT declared leakage-free:
  an unknown relationship cannot be proven absent, only isolated.
* Subjects observed on both sides of the time cutoff are "cutoff-crossing".
  Default policy quarantines them; policies that force them to one side are
  supported but the resulting time-condition violations are reported instead
  of being hidden.
* Pre-cutoff-only subjects are stratified by label with a seeded
  ``StratifiedShuffleSplit``; rare labels that cannot be placed on both sides
  fall back to a seeded per-label allocation and every deviation from the
  target ratio is reported numerically.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from sklearn.model_selection import StratifiedShuffleSplit

TRAIN = "train"
EVAL = "eval"
EXCLUDED = "excluded"

VALID_CUTOFF_POLICIES = {"exclude", "eval", "train"}


@dataclass
class SplitParams:
    cutoff_date: datetime
    target_eval_ratio: float
    seed: int
    cutoff_policy: str = "exclude"
    target_label_ratios: dict | None = None
    subject_field: str = "subject_id"

    def __post_init__(self):
        if not 0.0 <= float(self.target_eval_ratio) <= 1.0:
            raise ValueError("target_eval_ratio must be within [0, 1]")
        if self.cutoff_policy not in VALID_CUTOFF_POLICIES:
            raise ValueError(
                f"cutoff_policy must be one of {sorted(VALID_CUTOFF_POLICIES)}"
            )
        if self.subject_field != "subject_id":
            # The inventory models the subject explicitly; other columns are not
            # subjects and must not silently be used as identity.
            raise ValueError("only subject_field='subject_id' is supported")


def _to_dt(value) -> pd.Timestamp:
    return pd.Timestamp(value).tz_localize(None) if pd.Timestamp(value).tzinfo else pd.Timestamp(value)


def resolve_provenance(df: pd.DataFrame) -> pd.DataFrame:
    """Walk each sample's source chain to its original sample.

    Adds effective_subject_key / root_code / provenance flags. Cycles and
    dangling references are detected rather than guessed at.
    """
    by_code = df.set_index("sample_code")
    source_of = dict(zip(df["sample_code"], df["source_sample_code"]))
    own_subject = dict(zip(df["sample_code"], df["subject_key"]))

    effective_subject: dict[str, str | None] = {}
    root_of: dict[str, str | None] = {}
    depth_of: dict[str, int] = {}

    for code in df["sample_code"]:
        seen: list[str] = []
        cur = code
        cycle = False
        while True:
            if cur in seen:
                cycle = True
                break
            seen.append(cur)
            nxt = source_of.get(cur)
            if nxt is None or (isinstance(nxt, float) and pd.isna(nxt)):
                break  # cur is an original sample
            if nxt not in source_of:
                cur = "__MISSING__"  # dangling reference
                break
            cur = nxt

        row_reasons = []
        if cycle:
            row_reasons.append("source_cycle")
            effective_subject[code] = None
            root_of[code] = None
            depth_of[code] = len(seen)
        elif cur == "__MISSING__":
            row_reasons.append("missing_source_ref")
            effective_subject[code] = None
            root_of[code] = None
            depth_of[code] = len(seen)
        else:
            root_of[code] = cur
            depth_of[code] = len(seen) - 1
            root_subject = own_subject.get(cur)
            if isinstance(root_subject, float) and pd.isna(root_subject):
                root_subject = None
            effective_subject[code] = root_subject
            if depth_of[code] > 0:
                row_reasons.append("inherited_identity")
                if root_subject is None:
                    row_reasons.append("missing_subject")
            elif root_subject is None:
                row_reasons.append("missing_subject")
        df.loc[df["sample_code"] == code, "_reasons"] = ";".join(row_reasons)

    df = df.copy()
    df["effective_subject_key"] = df["sample_code"].map(effective_subject)
    df["root_code"] = df["sample_code"].map(root_of)
    df["chain_depth"] = df["sample_code"].map(depth_of)
    df["collected_naive"] = df["collected_at"].map(_to_dt)
    return df


def _primary_label(group: pd.DataFrame) -> str:
    counts = group["label"].value_counts()
    top = counts.max()
    return sorted(counts[counts == top].index)[0]


def _seeded_label_allocation(
    groups: pd.DataFrame, target_ratio: float, seed: int, label_targets: dict
) -> tuple[dict, list]:
    """Fallback allocation: seeded shuffle within each label, fill to target.

    Used when StratifiedShuffleSplit cannot run (label present in only one
    subject group). Returns group_key -> side and deviation notes.
    """
    import random

    rng = random.Random(seed)
    side: dict[str, str] = {}
    notes: list[str] = []
    for label, part in groups.groupby("primary_label"):
        ratio = float(label_targets.get(label, target_ratio))
        ordered = part.sample(frac=1.0, random_state=seed)
        total = int(ordered["n_samples"].sum())
        target_eval = round(total * ratio)
        got = 0
        for _, g in ordered.iterrows():
            if got < target_eval:
                side[g.name] = EVAL
                got += int(g.n_samples)
            else:
                side[g.name] = TRAIN
        if target_eval > 0 and got == 0:
            notes.append(f"rare_label_eval_unmet:{label}")
    return side, notes


def build_split(df: pd.DataFrame, params: SplitParams) -> dict:
    """Compute assignments and statistics from a samples DataFrame.

    Expected columns: sample_code, kind, label, collected_at, subject_key,
    source_sample_code.
    """
    df = df.copy()
    df["_reasons"] = ""
    df = resolve_provenance(df)
    cutoff = pd.Timestamp(params.cutoff_date)

    assignments: dict[str, dict] = {}
    for _, row in df.iterrows():
        reasons = [r for r in str(row["_reasons"]).split(";") if r]
        eff_subject = row["effective_subject_key"]
        if isinstance(eff_subject, float) and pd.isna(eff_subject):
            eff_subject = None
        assignments[row["sample_code"]] = {
            "sample_code": row["sample_code"],
            "effective_subject_key": eff_subject,
            "assignment": EXCLUDED,
            "reasons": reasons,
            "inherited": bool(row["chain_depth"] > 0),
            "label": row["label"],
            "collected_at": row["collected_at"].isoformat()
            if hasattr(row["collected_at"], "isoformat")
            else str(row["collected_at"]),
            "kind": row["kind"],
        }

    # ---- Step 1: quarantine samples with no provable origin identity --------
    known = df[df["effective_subject_key"].notna()].copy()
    known["is_pre"] = known["collected_naive"] < cutoff

    # ---- Step 2: subject groups --------------------------------------------
    group_rows = []
    for key, g in known.groupby("effective_subject_key", sort=True):
        group_rows.append(
            {
                "subject_key": key,
                "primary_label": _primary_label(g),
                "n_samples": len(g),
                "has_pre": bool(g["is_pre"].any()),
                "has_post": bool((~g["is_pre"]).any()),
                "labels": sorted(g["label"].unique().tolist()),
            }
        )
    groups = pd.DataFrame(group_rows).set_index("subject_key")

    side_of_group: dict[str, str] = {}
    group_notes: dict[str, list] = defaultdict(list)
    global_notes: list[str] = []

    crossing = groups[groups["has_pre"] & groups["has_post"]]
    post_only = groups[groups["has_post"] & ~groups["has_pre"]]
    pre_only = groups[groups["has_pre"] & ~groups["has_post"]]

    # ---- Step 3: cutoff-crossing subjects -----------------------------------
    for key in crossing.index:
        if params.cutoff_policy == "exclude":
            side_of_group[key] = EXCLUDED
            group_notes[key].append("cutoff_crossing")
        elif params.cutoff_policy == "eval":
            side_of_group[key] = EVAL
            group_notes[key].append("cutoff_crossing")
            group_notes[key].append("forced_eval_by_policy")
            group_notes[key].append("eval_contains_pre_cutoff")
        else:  # train
            side_of_group[key] = TRAIN
            group_notes[key].append("cutoff_crossing")
            group_notes[key].append("forced_train_by_policy")
            group_notes[key].append("train_after_cutoff_violation")

    # Post-cutoff-only subjects are forced to eval by the time condition.
    for key in post_only.index:
        side_of_group[key] = EVAL
        group_notes[key].append("post_cutoff_group")

    # ---- Step 4: seeded stratified allocation of pre-cutoff-only groups ----
    rare_notes: list[str] = []
    if len(pre_only):
        label_counts = pre_only["primary_label"].value_counts()
        stratifiable = pre_only.index[
            pre_only["primary_label"].map(label_counts) >= 2
        ]
        singleton_labels = sorted(
            pre_only.loc[~pre_only.index.isin(stratifiable), "primary_label"]
            .unique()
            .tolist()
        )
        pool = pre_only.loc[stratifiable]
        single_pool = pre_only.loc[~pre_only.index.isin(stratifiable)]
        if len(pool):
            sss = StratifiedShuffleSplit(
                n_splits=1,
                test_size=float(params.target_eval_ratio),
                random_state=int(params.seed),
            )
            idx = pool.index.to_numpy()
            y = pool["primary_label"].to_numpy()
            try:
                _, eval_idx = next(sss.split(idx, y))
                eval_keys = set(idx[eval_idx])
                for key in pool.index:
                    side_of_group[key] = EVAL if key in eval_keys else TRAIN
            except ValueError as exc:  # pragma: no cover - defensive
                global_notes.append(f"stratified_split_failed:{exc}")
                sides, rare_notes = _seeded_label_allocation(
                    pool,
                    params.target_eval_ratio,
                    params.seed,
                    params.target_label_ratios or {},
                )
                side_of_group.update(sides)
        if singleton_labels:
            global_notes.append(
                "rare_single_group_labels:" + ",".join(singleton_labels)
            )
        # Labels carried by a single subject group cannot be stratified; use a
        # seeded per-label allocation and report the deviation instead.
        if len(single_pool):
            sides, notes = _seeded_label_allocation(
                single_pool,
                params.target_eval_ratio,
                params.seed + 1,
                params.target_label_ratios or {},
            )
            side_of_group.update(sides)
            rare_notes.extend(notes)
    global_notes.extend(sorted(set(rare_notes)))

    # ---- Step 5: map group sides back onto individual samples --------------
    code_to_subject = dict(zip(known["sample_code"], known["effective_subject_key"]))
    for code, subject in code_to_subject.items():
        side = side_of_group.get(subject, EXCLUDED)
        assignments[code]["assignment"] = side
        assignments[code]["reasons"].extend(group_notes.get(subject, []))
        if side == TRAIN:
            assignments[code]["reasons"].append("pre_cutoff_group")

    # ---- Step 6: statistics and explicit leakage assertions ----------------
    assigned = df[
        df["sample_code"].map(lambda c: assignments[c]["assignment"]).isin([TRAIN, EVAL])
    ].copy()
    assigned["side"] = assigned["sample_code"].map(
        lambda c: assignments[c]["assignment"]
    )
    assigned["is_pre"] = assigned["collected_naive"] < cutoff

    total_used = len(assigned)
    eval_n = int((assigned["side"] == EVAL).sum())
    train_n = int((assigned["side"] == TRAIN).sum())
    actual_ratio = round(eval_n / total_used, 4) if total_used else 0.0

    per_label = {}
    for label, part in assigned.groupby("label"):
        e = int((part["side"] == EVAL).sum())
        target = float((params.target_label_ratios or {}).get(label, params.target_eval_ratio))
        per_label[label] = {
            "total": int(len(part)),
            "eval": e,
            "train": int(len(part) - e),
            "actual_eval_ratio": round(e / len(part), 4) if len(part) else 0.0,
            "target_eval_ratio": target,
            "diff": round((e / len(part) - target) if len(part) else 0.0, 4),
        }

    # Subject isolation proof: no subject on both sides.
    sides_by_subject = assigned.groupby("effective_subject_key")["side"].nunique()
    isolation_ok = bool((sides_by_subject <= 1).all())

    # Time-condition checks.
    # train must never contain anything at/after the cutoff.
    train_after = assigned[(assigned["side"] == TRAIN) & (~assigned["is_pre"])]
    # eval receiving a deliberately-allocated pre-cutoff subject is normal
    # (ratio balancing). It is reported for transparency, not a violation.
    eval_before = assigned[(assigned["side"] == EVAL) & (assigned["is_pre"])]
    eval_before_forced = assigned[
        (assigned["side"] == EVAL)
        & (assigned["is_pre"])
        & (
            assigned["sample_code"].map(
                lambda c: "eval_contains_pre_cutoff" in assignments[c]["reasons"]
            )
        )
    ]

    conflict_counts: dict[str, int] = defaultdict(int)
    for item in assignments.values():
        for r in item["reasons"]:
            if r in {
                "missing_source_ref",
                "source_cycle",
                "missing_subject",
                "cutoff_crossing",
                "train_after_cutoff_violation",
                "eval_contains_pre_cutoff",
            }:
                conflict_counts[r] += 1

    unknown_total = int(df["effective_subject_key"].isna().sum())
    quarantined_codes = {
        c
        for c, a in assignments.items()
        if a["assignment"] == EXCLUDED
        and any(
            r in a["reasons"]
            for r in ("missing_source_ref", "source_cycle", "missing_subject")
        )
    }

    stats = {
        "total_samples": int(len(df)),
        "used_samples": total_used,
        "excluded_samples": int(len(df) - total_used),
        "train_samples": train_n,
        "eval_samples": eval_n,
        "total_subjects": int(len(groups)),
        "cutoff_crossing_subjects": int(len(crossing)),
        "target_eval_ratio": float(params.target_eval_ratio),
        "actual_eval_ratio": actual_ratio,
        "ratio_diff": round(actual_ratio - float(params.target_eval_ratio), 4),
        "per_label": per_label,
        "conflict_counts": dict(conflict_counts),
        "notes": sorted(set(global_notes)),
        "assertions": {
            # True only when verifiable. Unknown provenance is quarantined,
            # never certified as safe.
            "subject_isolation": isolation_ok,
            "train_before_cutoff_only": int(len(train_after)) == 0,
            "unknown_provenance_quarantined": len(quarantined_codes)
            == unknown_total,
        },
        "time_condition": {
            # Hard rule: zero train samples at/after cutoff.
            "train_samples_after_cutoff": int(len(train_after)),
            # Forced leak under unsafe cutoff policy (if any).
            "forced_pre_cutoff_samples_in_eval": int(len(eval_before_forced)),
            # Pre-cutoff subjects deliberately placed in eval for ratio
            # balancing. Allowed and reported; the train side stays temporal.
            "balanced_pre_cutoff_samples_in_eval": int(
                len(eval_before) - len(eval_before_forced)
            ),
            "post_cutoff_groups_forced_eval": int(len(post_only)),
        },
        "unresolved_relationships": unknown_total,
        "seed": int(params.seed),
        "cutoff_policy": params.cutoff_policy,
    }
    return {
        "params": {
            "cutoff_date": str(cutoff.date()),
            "target_eval_ratio": float(params.target_eval_ratio),
            "target_label_ratios": params.target_label_ratios or {},
            "seed": int(params.seed),
            "cutoff_policy": params.cutoff_policy,
            "subject_field": params.subject_field,
        },
        "assignments": [assignments[c] for c in df["sample_code"]],
        "stats": stats,
    }
