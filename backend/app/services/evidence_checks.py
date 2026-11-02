"""Conservative checks: a mentioned method is not an observed outcome."""
from __future__ import annotations

import json
import re

from app.models.evidence import MaterialRole


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
            or doc.origin == "followup_answer"):
        return False
    # A count setting, seed, or 'mean ± std' does not contain measured variability.
    return bool(re.search(r"\d+(?:\.\d+)?\s*±\s*\d+(?:\.\d+)?", fact.effective_value()))
