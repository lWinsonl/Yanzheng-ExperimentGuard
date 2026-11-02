"""Compute facts from complete confirmed records, never from model suggestions."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re

from app.models.checks import ProgramCheck, RepairCheck
from app.models.evidence import MaterialKind, MaterialRole
from app.services.evidence_checks import entity_sets
from app.services.numeric_evidence import evaluate_fact


def parse_confusion_table(raw):
    """Explicit binary labels only; do not guess column orientation or positive class."""
    try:
        reader = csv.DictReader(io.StringIO(raw.strip()))
        fields = reader.fieldnames
        if fields == ["Observed", "Predicted0", "Predicted1"]:
            columns = ("Predicted0", "Predicted1")
        elif fields == ["Observed", "0", "1"]:
            columns = ("0", "1")
        else:
            return None
        rows = list(reader)
        if len(rows) != 2 or any(set(r) != set(fields) for r in rows) or {r["Observed"] for r in rows} != {"0", "1"}:
            return None
        if any(not isinstance(r.get(c), str) or not re.fullmatch(r"\d{1,12}", r[c]) for r in rows for c in columns):
            return None
        rows = {r["Observed"]: r for r in rows}
        tn, fp = (int(rows["0"][c]) for c in columns)
        fn, tp = (int(rows["1"][c]) for c in columns)
        return dict(TN=tn, FP=fp, FN=fn, TP=tp)
    except (csv.Error, KeyError, TypeError):
        return None


def original_record(fact, docs):
    doc = docs.get(fact.source.material_id)
    if (not fact.is_usable() or doc is None or doc.role != MaterialRole.EXECUTION
            or doc.kind == MaterialKind.CODE or doc.origin != "uploaded" or doc.ocr_required
            or not fact.source.verify(doc) or fact.effective_value().strip() != fact.source.snippet.strip()):
        return None
    if re.search(r"示例|模板|未运行|未执行|example\s+(?:only|data)|not\s+(?:run|executed)", doc.content, re.I):
        return None
    return doc


def build_checks(facts, docs, claims):
    checks, seen = [], set()
    for fact in facts:
        doc = original_record(fact, docs)
        if doc is None:
            continue
        raw = fact.effective_value()
        digest = hashlib.sha256(raw.encode()).hexdigest()
        if (doc.material_id, digest) in seen:
            continue
        seen.add((doc.material_id, digest))
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            obj = None
        declared = obj.get("evaluation_scope", "") if isinstance(obj, dict) else ""
        declared = declared.strip() if isinstance(declared, str) and len(declared) <= 200 else ""
        if declared.lower() in {"unknown", "n/a", "未知", "待定"}:
            declared = ""

        def add(kind, title, status, basis, values, scope_suffix=""):
            # Filename is a matching hint, not proof that two experiments share a scope.
            scope_key = f"{kind}:{doc.role.value}:{doc.filename}:{scope_suffix}"
            check_id = "check_" + hashlib.sha256((scope_key + doc.material_id + digest).encode()).hexdigest()[:16]
            checks.append(ProgramCheck(check_id=check_id, kind=kind, scope_key=scope_key,
                scope_identity=declared, title=title, status=status, basis=basis, values=values,
                fact_ids=[fact.fact_id], material_ids=[doc.material_id]))

        sets = entity_sets(raw)
        if sets:
            train, test = sets
            overlap = sorted(train & test)
            add("entity_isolation", "训练与测试实体编号交集", "failed" if overlap else "passed",
                f"完整读取所提供的两份编号列表：训练{len(train)}个、测试{len(test)}个，交集{len(overlap)}个。"
                + ("存在同源实体，当前记录未通过隔离检查。" if overlap else "这些列表未出现相同编号；不据此排除其他泄漏。"),
                dict(train_entities=len(train), test_entities=len(test), overlap_count=len(overlap), overlap_examples=overlap[:10]))

        matrix = parse_confusion_table(raw)
        if matrix and any(re.search(r"\brecall\b|召回率", c, re.I) for c in claims):
            denominator = matrix["TP"] + matrix["FN"]
            recall = matrix["TP"] / denominator if denominator else None
            add("recall_defined", "二分类召回率分母", "passed" if denominator else "failed",
                f"按表中Observed=1为正类、行为真实值、列为预测值：TP+FN={denominator}。"
                + (f"该表的recall={recall:.6g}；这不是总体性能证明。" if denominator else "正类为零，recall未定义，不能写成0、100%或用准确率代替。"),
                dict(**matrix, positive_label=1, denominator=denominator, recall=recall))

        for claim in claims:
            for aspect in ("comparison", "stability"):
                result = evaluate_fact(fact, docs, aspect, claim)
                if result is not None:
                    status = {"supports": "passed", "contradicts": "failed", "unknown": "unknown"}[result[0]]
                    add(aspect, "限定数值比较" if aspect == "comparison" else "所报告运行的波动比较",
                        status, result[1], {"claim": claim, "relation": result[0]}, hashlib.sha256(claim.encode()).hexdigest()[:12])
    return checks


def compare_repair_checks(old_checks, new_checks):
    """Only re-evaluate recorded failed predicates. Missing evidence never proves repair."""
    result = []
    for before in old_checks:
        if before.status != "failed":
            continue
        matches = [c for c in new_checks if c.scope_key == before.scope_key]
        current = matches[0] if len(matches) == 1 else None
        status, detail = "not_verified", "缺少唯一、已确认的对应新记录；不能把删除材料或口头说明当作修复。"
        if current:
            if before.scope_identity and current.scope_identity and before.scope_identity != current.scope_identity:
                detail = "前后声明的实验范围不同，不能用新实验替代原问题的验证。"
            elif current.status == "failed":
                status, detail = "still_fails", "新记录仍未通过同一检查：" + current.basis
            elif current.status == "passed":
                if before.scope_identity and before.scope_identity == current.scope_identity:
                    status = "passed_on_records"
                    detail = "同一声明范围的新记录通过此项检查；未独立验证范围声明、实际训练过程与其他风险。"
                else:
                    status = "scope_unconfirmed"
                    detail = "当前记录通过此项检查，但前后缺少一致的evaluation_scope声明，尚不能确认是原实验的修复。"
        result.append(RepairCheck(kind=before.kind, title=before.title, status=status,
            before_check_id=before.check_id, after_check_id=current.check_id if current else "",
            before_values=before.values, after_values=current.values if current else {}, detail=detail))
    return result
