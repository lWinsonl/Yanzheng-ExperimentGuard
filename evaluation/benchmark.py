"""Exercise the current rule + extraction + confirmed-fact + graph pipeline offline."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import statistics
import time

from .metrics import summarize


def load_dataset(path):
    raw = Path(path).read_bytes()
    dataset = json.loads(raw)
    ids = [c["case_id"] for c in dataset["cases"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate case_id in dataset")
    return dataset, hashlib.sha256(raw).hexdigest()


def run_offline(dataset_path: Path, data_dir: Path):
    # Imported only after the process has explicitly disabled all LLM credentials.
    from app.agent.llm_client import llm_client
    from app.models.evidence import FactStatus
    from app.services import claim_graph_service, data_store, evidence_chain, review_service

    if llm_client.is_available():
        raise RuntimeError("Offline benchmark refuses to run with model calls enabled")
    dataset, digest = load_dataset(dataset_path)
    rows = []
    for case in dataset["cases"]:
        started = time.perf_counter()
        row = {"case_id": case["case_id"], "project_id": case["project_id"],
               "domain": case["domain"], "aspect": case["aspect"], "gold": case["gold"],
               "prediction": "error", "rationale": case["rationale"],
               "citations": 0, "valid_citations": 0}
        try:
            session = evidence_chain.create_session(case["case_id"], case["domain"], [case["claim"]])
            sid = session.session_id
            for material in case["materials"]:
                evidence_chain.extract_from_text(sid, material["content"], material["filename"], material["role"])
            store = data_store.require(sid)
            for fact in list(store.facts.values()):
                if fact.status == FactStatus.PENDING:
                    evidence_chain.confirm_fact(sid, fact.fact_id, "confirm")
            report = review_service.run_review(sid)
            graph = claim_graph_service.build_graph(sid)
            subs = [s for s in graph.sub_claims if s.test_aspect.value == case["aspect"] and s.status.value != "rejected"]
            active_edges = [edge for sub in subs for edge in graph.edges_for_sub_claim(sub.sub_claim_id)]
            conclusive = {e.effective_relation().value for e in active_edges if e.effective_relation().value != "unknown"}
            row["prediction"] = ("supported" if conclusive == {"supports"} else
                                 "contradicted" if conclusive == {"contradicts"} else "insufficient")
            row["missing_target_subclaim"] = not subs
            row["conflicting_edges"] = len(conclusive) > 1
            row["edge_bases"] = [e.basis for e in active_edges]
            row["extracted_facts"] = len(store.facts)
            row["rule_findings"] = [{"rule_id": f.rule_id, "level": f.level.value, "title": f.title} for f in report.findings]
            # Count all emitted refs. A real anchor is not proof the inference is correct.
            refs = [(f.source, f) for f in store.facts.values()]
            for finding in report.findings:
                refs.extend((ref.source, store.facts.get(ref.fact_id)) for ref in finding.evidence)
            for edge in active_edges:
                if edge.fact_id:
                    fact = store.facts.get(edge.fact_id)
                    if fact:
                        refs.append((fact.source, fact))
                    else:
                        row["citations"] += 1
            for span, fact in refs:
                row["citations"] += 1
                doc = store.docs.get(span.material_id)
                row["valid_citations"] += int(bool(fact and fact.is_usable() and doc and span.verify(doc)))
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        row["latency_ms"] = (time.perf_counter() - started) * 1000
        row["correct"] = row["prediction"] == row["gold"]
        rows.append(row)
    latencies = sorted(r["latency_ms"] for r in rows)
    summary = summarize(rows)
    by_aspect = {aspect: summarize([r for r in rows if r["aspect"] == aspect]) for aspect in sorted({r["aspect"] for r in rows})}
    by_domain = {domain: summarize([r for r in rows if r["domain"] == domain]) for domain in sorted({r["domain"] for r in rows})}
    return {"dataset_id": dataset["dataset_id"], "dataset_sha256": digest,
            "dataset_status": dataset["status"], "condition": "offline_rule_pipeline",
            "model_calls": 0, "summary": summary, "by_aspect": by_aspect, "by_domain": by_domain,
            "latency": {"median_ms": statistics.median(latencies),
                        "nearest_rank_p95_ms": latencies[max(0, math.ceil(.95 * len(latencies)) - 1)],
                        "scope": "本机串行、含提取/确认/JSON保存；无网络、非生产性能SLA"},
            "cases": rows,
            "warning": "公开合成开发探针；全部事实由脚本确认。不能解释为真实科研准确率、端到端模型效果或学生学习效果。"}
