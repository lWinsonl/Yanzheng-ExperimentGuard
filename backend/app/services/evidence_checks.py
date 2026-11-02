"""Conservative checks: a mentioned method is not an observed outcome."""
from __future__ import annotations

import json
import re

from app.models.evidence import MaterialKind, MaterialRole


def entity_sets(text: str) -> tuple[set[str], set[str]] | None:
    """Accept explicit, nonempty entity lists; never infer them from function names."""
    try:
        obj = json.loads(text.strip())
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    lists = [obj.get(k) for k in ("train_entity_ids", "test_entity_ids")]
    if any(not isinstance(v, list) or not v for v in lists):
        return None
    if any(isinstance(x, bool) or not isinstance(x, (str, int)) or str(x) == ""
           for values in lists for x in values):
        return None
    return tuple(set(str(x) for x in values) for values in lists)


def entity_overlap(fact, docs) -> set[str] | None:
    doc = docs.get(fact.source.material_id)
    if (doc is None or doc.role != MaterialRole.EXECUTION
            or doc.origin == "followup_answer" or not fact.source.verify(doc)):
        return None
    if fact.effective_value().strip() != fact.source.snippet.strip():
        return None  # A corrected interpretation is not a replacement execution record.
    sets = entity_sets(fact.source.snippet)
    return sets[0] & sets[1] if sets else None


def observed_repetitions(fact, docs) -> bool:
    doc = docs.get(fact.source.material_id)
    if (doc is None or doc.role != MaterialRole.EXECUTION
            or doc.origin == "followup_answer" or doc.kind == MaterialKind.CODE
            or doc.ocr_required or not fact.source.verify(doc)):
        return False
    if doc.kind == MaterialKind.CONFIG:
        from app.services.numeric_evidence import has_run_observation
        return has_run_observation(fact, docs)
    # A nearby example, future tense or negation cannot be an observed run.
    context = doc.content[max(0, fact.source.start_char - 120):fact.source.end_char + 120]
    if re.search(r"示例|模板|未运行|尚未|计划|预计|将(?:会|要)?|example|template|not\s+(?:run|executed)|planned", context, re.I):
        return False
    measured = re.search(r"\d+(?:\.\d+)?\s*±\s*\d+(?:\.\d+)?", fact.effective_value())
    # Extraction keeps a short value plus a longer source context. Require the
    # observed numbers in that verified source, not equality of these two fields.
    # User corrections cannot invent a measurement missing from the upload.
    if not measured or measured.group(0) not in fact.source.snippet:
        return False
    count = re.search(r"(?:n[_-]?runs|n_repeats)\s*[:=]\s*([2-9]\d*|1\d+)|(?:重复|运行)\s*([2-9]\d*|1\d+)\s*次|\b([2-9]\d*|1\d+)\s*runs?\b", fact.source.snippet, re.I)
    return bool(measured and count)
