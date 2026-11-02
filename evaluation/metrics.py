"""Metrics deliberately expose abstention, errors and empty denominators."""
from __future__ import annotations

from collections import Counter
import math
import random
import statistics

LABELS = ("supported", "contradicted", "insufficient")


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def wilson(successes: int, total: int, z: float = 1.959963984540054):
    if total == 0:
        return None
    if not 0 <= successes <= total:
        raise ValueError("Invalid binomial counts")
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - half), min(1.0, center + half)]


def summarize(rows: list[dict], independent_units: bool = False) -> dict:
    """Rows must be one prediction per case, not repeated runs as independent cases."""
    ids = [row["case_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate cases; summarize repeated runs separately")
    if any(row["gold"] not in LABELS or row["prediction"] not in (*LABELS, "error") for row in rows):
        raise ValueError("Unknown label")
    matrix = {label: {pred: 0 for pred in (*LABELS, "error")} for label in LABELS}
    for row in rows:
        matrix[row["gold"]][row["prediction"]] += 1
    by_class = {}
    for label in LABELS:
        tp = matrix[label][label]
        fp = sum(matrix[other][label] for other in LABELS if other != label)
        fn = sum(count for pred, count in matrix[label].items() if pred != label)
        # F1 is 0 when class exists but has no correct predictions; undefined only for an absent class.
        by_class[label] = dict(tp=tp, fp=fp, fn=fn,
            precision=ratio(tp, tp + fp), recall=ratio(tp, tp + fn),
            f1=ratio(2 * tp, 2 * tp + fp + fn), support=sum(matrix[label].values()))
    decidable = [r for r in rows if r["gold"] != "insufficient"]
    answered_decidable = [r for r in decidable if r["prediction"] in ("supported", "contradicted")]
    conclusive = [r for r in rows if r["prediction"] in ("supported", "contradicted")]
    correct_conclusive = sum(r["prediction"] == r["gold"] for r in conclusive)
    false_conclusive = len(conclusive) - correct_conclusive
    abstention_on_decidable = sum(r["prediction"] == "insufficient" for r in decidable)
    insufficient = [r for r in rows if r["gold"] == "insufficient"]
    class_f1 = [v["f1"] for v in by_class.values() if v["f1"] is not None]
    valid_citations = sum(r.get("valid_citations", 0) for r in rows)
    citations = sum(r.get("citations", 0) for r in rows)
    return {
        "n_cases": len(rows), "label_counts": dict(Counter(r["gold"] for r in rows)),
        "confusion_matrix": matrix, "per_class": by_class,
        "accuracy": ratio(sum(r["gold"] == r["prediction"] for r in rows), len(rows)),
        "macro_f1": statistics.mean(class_f1) if class_f1 else None,
        "decidable_cases": len(decidable), "conclusive_cases": len(conclusive),
        "decision_coverage": ratio(len(answered_decidable), len(decidable)),
        "abstention_on_decidable": ratio(abstention_on_decidable, len(decidable)),
        "selective_accuracy": ratio(correct_conclusive, len(conclusive)),
        "false_conclusive_count": false_conclusive,
        "false_conclusive_rate": ratio(false_conclusive, len(conclusive)),
        "insufficient_recognition": ratio(sum(r["prediction"] == "insufficient" for r in insufficient), len(insufficient)),
        "execution_error_count": sum(r["prediction"] == "error" for r in rows),
        "citations": citations, "valid_citations": valid_citations,
        "anchor_validity": ratio(valid_citations, citations),
        # For descriptive synthetic suites use raw counts. Only apply Wilson to independent adjudicated units.
        "unit_accuracy_wilson95": wilson(sum(r["gold"] == r["prediction"] for r in rows), len(rows)) if independent_units else None,
    }


def cohen_kappa(first: list[str], second: list[str]):
    if len(first) != len(second) or not first:
        raise ValueError("Two equally sized nonempty independent label lists required")
    n = len(first)
    a, b = Counter(first), Counter(second)
    observed = sum(x == y for x, y in zip(first, second)) / n
    expected = sum(a[k] * b[k] for k in a.keys() | b.keys()) / (n * n)
    return (observed - expected) / (1 - expected) if expected < 1 else None


def paired_cluster_bootstrap(rows: list[dict], repeats=2000, seed=20261102):
    """Difference in case accuracy A-B, resampling projects, keeping pairs and repeated runs together.

    Each row is a single case/run pair {project_id, correct_a, correct_b}. Within
    project average first; the estimand gives equal weight to projects, not files.
    """
    if repeats < 100:
        raise ValueError("Use at least 100 bootstrap resamples")
    grouped = {}
    for row in rows:
        if not row.get("project_id"):
            raise ValueError("project_id required; do not resample correlated files independently")
        if any(type(row.get(k)) is not bool for k in ("correct_a", "correct_b")):
            raise ValueError("Correctness must be boolean")
        grouped.setdefault(row["project_id"], []).append(int(row["correct_a"]) - int(row["correct_b"]))
    values = [statistics.mean(v) for v in grouped.values()]
    if len(values) < 2:
        return {"projects": len(values), "difference": statistics.mean(values) if values else None,
                "interval95": None, "note": "至少需要两个独立项目，且小样本区间不稳定"}
    rng = random.Random(seed)
    samples = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(repeats))
    return {"projects": len(values), "difference": statistics.mean(values),
            "interval95": [samples[int(0.025 * (repeats - 1))], samples[int(0.975 * (repeats - 1))]],
            "resamples": repeats, "seed": seed, "estimand": "equal_weight_project_mean_accuracy_difference"}
