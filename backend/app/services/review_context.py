"""Build bounded, ID-addressable evidence and exact program results for deep review."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

from app.services.program_checks import build_checks


@dataclass
class ReviewEvidence:
    evidence_id: str
    material_id: str
    filename: str
    role: str
    start_char: int
    end_char: int
    text: str
    source_kind: str = "uploaded_excerpt"
    check_id: str = ""


@dataclass
class EvidenceContext:
    evidence: list[ReviewEvidence] = field(default_factory=list)
    checks: list = field(default_factory=list)
    coverage: list[dict] = field(default_factory=list)

    def prompt_text(self):
        return json.dumps({"evidence_catalog": [asdict(e) for e in self.evidence],
                           "program_checks": [c.model_dump(mode="json") for c in self.checks[:24]],
                           "omitted_check_count": max(0, len(self.checks)-24)}, ensure_ascii=False)


def build_context(store, budget=8000):
    context = EvidenceContext(checks=build_checks(store.usable_facts(), store.docs, [c.text for c in store.session.claims]))
    used = 0
    computed_docs = {mid for c in context.checks for mid in c.material_ids}
    for doc in store.docs.values():
        text, ranges = doc.content, []
        if len(text) <= 2000:
            candidates = [(start, min(start + 600, len(text))) for start in range(0, len(text), 600)]
        else:
            # Full structured records are checked by program; don't feed thousands
            # of IDs to the model or imply that the excerpt alone proves absence.
            candidates = [(0, min(len(text), 200 if doc.material_id in computed_docs else 600))]
            if doc.material_id not in computed_docs:
                for fact in store.usable_facts():
                    if fact.source.material_id == doc.material_id and fact.source.verify(doc):
                        start = max(0, fact.source.start_char - 80)
                        if not any(a <= start < b for a, b in candidates):
                            candidates.append((start, min(start + 600, len(text))))
                        if len(candidates) == 3:
                            break
        for start, end in candidates:
            if len(context.evidence) >= 48:
                break
            # Remove overlapping ranges so coverage reports union length truthfully.
            for a, b in sorted(ranges):
                if a <= start < b:
                    start = b
                if start < a < end:
                    end = a
            if end <= start or used + end - start > budget:
                continue
            snippet = text[start:end]
            ident = "ev_" + hashlib.sha256(f"{doc.material_id}:{start}:{end}:{snippet}".encode()).hexdigest()[:16]
            context.evidence.append(ReviewEvidence(ident, doc.material_id, doc.filename, doc.role.value, start, end, snippet))
            ranges.append((start, end))
            used += end - start
        count = sum(b-a for a, b in ranges)
        context.coverage.append(dict(material_id=doc.material_id, filename=doc.filename, role=doc.role.value,
            total_chars=len(text), checked_chars=count, truncated=count < len(text), selection_mode="selected_evidence",
            ranges=[{"start_char": a, "end_char": b} for a, b in sorted(ranges)]))
    # Link each computed result to its original record; this is an observation,
    # not a model-generated quote. Values are already validated by the program.
    for check in context.checks[:24]:
        for mid in check.material_ids:
            doc = store.docs[mid]
            text = check.basis + " " + json.dumps(check.values, ensure_ascii=False)
            ident = "ev_" + hashlib.sha256((check.check_id + text).encode()).hexdigest()[:16]
            context.evidence.append(ReviewEvidence(ident, mid, doc.filename, doc.role.value, 0, len(doc.content),
                text, source_kind="program_result", check_id=check.check_id))
    return context
