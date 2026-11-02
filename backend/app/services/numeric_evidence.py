"""Validate bounded numerical observations; never infer population superiority.

Only a confirmed whole observation from an execution document participates.
Known metric direction, method identity, scope and comparable conditions are
checked separately from arithmetic. JSON and explicit-column CSV are supported.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import statistics

from app.models.evidence import MaterialKind, MaterialRole

_HIGH = {"f1", "f1score", "accuracy", "precision", "recall", "auc", "auroc", "throughput", "qps", "准确率", "召回率"}
_LOW = {"rmse", "mse", "mae", "latency", "latencyms", "runtime", "runtimems", "memorymb", "error", "延迟", "均方根误差"}
_PROB = {"f1", "f1score", "accuracy", "precision", "recall", "auc", "auroc", "准确率", "召回率"}
_NUMERIC_KEYS = {"main_value", "baseline_value", "runs", "main_std", "baseline_std", "main_mean", "baseline_mean"}


def parsed_records(raw):
    records = []
    try:
        obj = json.loads(raw)
        objects = obj if isinstance(obj, list) else [obj]
        for item in objects:
            if not isinstance(item, dict):
                continue
            for kind in ("comparison", "stability"):
                values = item.get(kind, [])
                for value in values if isinstance(values, list) else [values]:
                    if isinstance(value, dict):
                        records.append((kind, value))
            if item.get("task_type") in ("comparison", "stability"):
                records.append((item["task_type"], item))
        return records
    except (ValueError, TypeError):
        pass
    try:
        for block in re.split(r"(?m)^--- 工作表：.*---\s*$", raw):
            lines = block.splitlines()
            header = next((i for i, line in enumerate(lines) if line.startswith("task_type,") or line.startswith("task_type\t")), None)
            if header is None:
                continue
            delimiter = "\t" if lines[header].startswith("task_type\t") else ","
            reader = csv.DictReader(io.StringIO("\n".join(lines[header:])), delimiter=delimiter)
            for row in reader:
                if row.get("task_type") not in ("comparison", "stability"):
                    continue
                normalized = dict(row)
                for key, value in row.items():
                    if key in ("executed", "is_example"):
                        normalized[key] = {"true": True, "false": False}.get((value or "").strip().lower())
                    if key in _NUMERIC_KEYS or (key and key.startswith(("sample_std_", "mean_"))):
                        try:
                            normalized[key] = float(value)
                        except (ValueError, TypeError):
                            normalized[key] = None
                records.append((row["task_type"], normalized))
    except (csv.Error, TypeError):
        return []
    return records


def confirmed_record(fact, docs):
    doc = docs.get(fact.source.material_id)
    if (doc is None or not fact.is_usable() or doc.role != MaterialRole.EXECUTION
            or doc.origin != "uploaded" or doc.kind == MaterialKind.CODE or doc.ocr_required
            or not fact.source.verify(doc)
            or fact.effective_value().strip() != fact.source.snippet.strip()):
        return []
    if re.search(r"示例|模板|未运行|未执行|尚未运行|计划运行|example\s+(?:only|data)|not\s+(?:run|executed)", doc.content, re.I):
        return []
    return parsed_records(fact.source.snippet)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def metric_name(value):
    return re.sub(r"[\s_\-]", "", value.lower()) if isinstance(value, str) else ""


def metric_matches_claim(metric, claim):
    aliases = {"f1score": "f1", "准确率": "accuracy", "召回率": "recall",
               "均方根误差": "rmse", "延迟": "latency"}
    mentioned = set()
    for name in _HIGH | _LOW:
        pattern = r"(?<![A-Za-z0-9_])" + r"[\s_-]*".join(map(re.escape, name)) + r"(?![A-Za-z0-9_])"
        if re.search(pattern, claim, re.I):
            mentioned.add(aliases.get(name, name))
    # One record cannot substantiate a different metric, an unspecified metric,
    # or a multi-metric conjunction. Such claims need clarification first.
    return mentioned == {aliases.get(metric, metric)}


def bounded_scope(claim, facet):
    # Explicit exclusions do not turn 'not claiming generalization' into a generalization claim.
    text = re.sub(r"(?:不涉及|不推断|不代表|不声称)[^。;；]*", "", claim)
    if re.search(r"显著|总体|未来|始终|所有|新设备|泛化|unseen|always|significan|generaliz|population", text, re.I):
        return False
    limited = bool(re.search(r"本次|表中|所报告|这[份些五\d]|固定测试|reported|in this|these", text, re.I))
    if facet == "stability":
        limited &= bool(re.search(r"标准差|sample.?std|standard deviation", text, re.I))
    return limited


def methods_match(claim, main, baseline):
    if re.search(r"(?:不|未)(?:优于|好于|超过|比)|not\s+better|not\s+outperform", claim, re.I):
        return False
    if any(not isinstance(name, str) or not name.strip() or len(name) > 60 for name in (main, baseline)) or main == baseline:
        return False
    # Require the declared direction A -> B, not just the presence of both names.
    prefix = r"(?:模型|方法|算法|系统|model\s*|method\s*|algorithm\s*)?\s*"
    main_part = r"(?<![A-Za-z0-9_])" + prefix + re.escape(main) + r"(?![A-Za-z0-9_])"
    base_part = r"(?:基线|baseline\s*)?\s*" + prefix + re.escape(baseline) + r"(?![A-Za-z0-9_])"
    return bool(re.search(main_part + r".{0,150}?(?:优于|好于|超过|强于|比|outperforms?|better\s+than)\s*" + base_part, claim, re.I))


def same_condition(value):
    if isinstance(value, str):
        return bool(re.fullmatch(r"same(?:_[a-z0-9_-]+)?|相同|一致", value.strip(), re.I))
    if isinstance(value, dict) and set(value) == {"main", "baseline"}:
        return (isinstance(value["main"], str) and bool(value["main"].strip())
                and value["main"].strip().lower() not in {"unknown", "different", "na", "n/a", "未知", "待定"}
                and value["main"] == value["baseline"])
    return False


def evaluate_comparison(record, claim):
    if not measured_record(record):
        return None
    if not bounded_scope(claim, "comparison") or not methods_match(claim, record.get("main_method"), record.get("baseline_method")):
        return None
    metric = metric_name(record.get("metric"))
    if not metric_matches_claim(metric, claim):
        return None
    expected = "higher" if metric in _HIGH else "lower" if metric in _LOW else None
    direction = record.get("better")
    if direction not in ("higher", "lower") or direction != expected:
        return None
    if not all(same_condition(record.get(k)) for k in ("test_split", "hardware", "preprocessing", "budget")):
        return None
    a, b = record.get("main_value"), record.get("baseline_value")
    if not number(a) or not number(b) or min(a, b) < 0:
        return None
    if metric in _PROB and max(a, b) > (100 if record.get("unit") == "percent" else 1):
        return None
    better = a > b if direction == "higher" else a < b
    better &= not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)
    relation = "supports" if better else "contradicts"
    basis = (f"在记录声明的相同划分、环境、预处理与预算下，{record['metric']}："
             f"{record['main_method']}={a}，{record['baseline_method']}={b}；"
             f"该指标{'越大' if direction == 'higher' else '越小'}越好。"
             "仅核对这些点估计，不推断显著性、其他测试或总体优势；未独立验证记录来源。")
    return relation, basis


def _stability_values(record, main, baseline):
    n = record.get("runs")
    if not number(n) or int(n) != n or not 2 <= n <= 10000:
        return None
    values = []
    for name, role in ((main, "main"), (baseline, "baseline")):
        mean = record.get("mean_" + name, record.get(role + "_mean"))
        std = record.get("sample_std_" + name, record.get(role + "_std"))
        runs = record.get("runs_" + name, record.get(role + "_runs"))
        if runs is not None:
            if not isinstance(runs, list) or len(runs) != n or not all(number(v) for v in runs):
                return None
            if min(runs) < 0 or metric_name(record.get("metric")) in _PROB and max(runs) > (100 if record.get("unit") == "percent" else 1):
                return None
            actual_mean, actual_std = statistics.mean(runs), statistics.stdev(runs)
            if (mean is not None and (not number(mean) or not math.isclose(mean, actual_mean, abs_tol=1e-8))
                    or std is not None and (not number(std) or not math.isclose(std, actual_std, abs_tol=1e-8))):
                return None
            mean, std = actual_mean, actual_std
        if not number(mean) or not number(std) or mean < 0 or std < 0:
            return None
        metric = metric_name(record.get("metric"))
        maximum = 100 if record.get("unit") == "percent" else 1
        if metric in _PROB and (mean > maximum or std * std > n / (n - 1) * mean * (maximum - mean) + 1e-9):
            return None
        values.append((mean, std))
    return n, values


def evaluate_stability(record, claim):
    if not measured_record(record):
        return None
    if not bounded_scope(claim, "stability") or metric_name(record.get("metric")) not in _HIGH | _LOW:
        return None
    if not metric_matches_claim(metric_name(record.get("metric")), claim):
        return None
    if record.get("conditions") not in ("same", "相同", "一致"):
        return None
    names = [(record.get("main_method"), record.get("baseline_method"))]
    if names == [(None, None)]:
        labels = [k[len("sample_std_"):] for k in record if k.startswith("sample_std_")]
        names = [(a, b) for a in labels for b in labels if a != b]
    pair = next(((a, b) for a, b in names if methods_match(claim, a, b)), None)
    if pair is None:
        return None
    measured = _stability_values(record, *pair)
    if measured is None:
        return None
    n, values = measured
    a, b = values[0][1], values[1][1]
    better = a < b and not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)
    return ("supports" if better else "contradicts",
            f"仅对所报告的同条件{int(n)}次运行，{record['metric']}样本标准差为{pair[0]}={a}、{pair[1]}={b}。"
            "据此核对该样本的波动大小，不证明未来更稳定、显著性或已排除偶然性；未独立验证运行记录来源。")


def evaluate_fact(fact, docs, aspect, claim):
    evaluator = evaluate_comparison if aspect == "comparison" else evaluate_stability
    results = [result for kind, record in confirmed_record(fact, docs)
               if kind == aspect and (result := evaluator(record, claim)) is not None]
    if not results:
        return None
    if len({relation for relation, _ in results}) > 1:
        return "unknown", "同一材料中存在支持与矛盾的多份记录，需先澄清适用测试，暂不合并为确定结论。"
    return results[0][0], "\n".join(basis for _, basis in results)


def has_run_observation(fact, docs):
    for kind, record in confirmed_record(fact, docs):
        if kind != "stability" or not measured_record(record):
            continue
        main, baseline = record.get("main_method"), record.get("baseline_method")
        if not main or not baseline:
            names = [k[len("sample_std_"):] for k in record if k.startswith("sample_std_")]
            if len(names) != 2:
                continue
            main, baseline = names
        if _stability_values(record, main, baseline) is not None:
            return True
    return False


def measured_record(record):
    return (record.get("executed", True) is True and record.get("is_example", False) is False
            and record.get("status") in (None, "observed", "completed", "executed", "ok"))
