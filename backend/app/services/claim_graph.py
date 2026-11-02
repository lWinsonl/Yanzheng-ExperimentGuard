"""主张—证据图构建服务。

职责:把"主张 + 已确认事实"变成"可校准的证据图"。

构建流程(全部确定性规则,不依赖模型):
1. 拆解:按主张中出现的模式词,拆出可检验子主张(scope/comparison/stability/...)。
2. 连边:对每个子主张,在已确认事实中找相关证据,构建边(supports/contradicts/unknown)。
   每条边必须绑定已验证锚点(用户确认/纠正的事实);无证据时标 missing_premise。
3. 反证检查:对每个子主张,显式检查替代解释与反证,
   严格区分"没找到反证"(no_counter_found)与"证明不存在反证"(counter_refuted)。

模型(LLM)的角色:只提出候选边/候选子主张(source=llm, status=pending),
由用户逐条确认后才生效——见 agent_service.propose_graph_candidates。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from app.models.claim import ExperimentType
from app.models.claim_graph import (
    ClaimEvidenceEdge,
    ClaimGraph,
    CounterEvidenceCheck,
    CounterProofStatus,
    EdgeRelation,
    EdgeSource,
    EdgeStatus,
    EvidenceDirection,
    SubClaim,
    TestAspect,
)
from app.models.evidence import ExtractedFact, FactCategory, MaterialRole
from app.services.store import data_store

logger = logging.getLogger("claim_graph")

# ---- 信号模式(与 data_model_rules 保持一致语义) ----
_GROUP_SPLIT_PATTERNS = [
    r"按\s*(设备|机器|机组|单元|组|用户|病人|被试)",
    r"GroupShuffleSplit", r"GroupKFold", r"group\s*=",
]
_RECORD_SPLIT_PATTERNS = [
    r"train_test_split", r"(随机|按记录|按样本|按条)", r"shuffle\s*=\s*True",
]
_NEW_ENTITY_PATTERNS = [r"新\s*(设备|机器|用户|病人|场景|领域)", r"未见", r"unseen", r"new\s+(device|machine|user)"]
_STABILITY_PATTERNS = [r"更?稳定", r"鲁棒", r"robust", r"stable", r"consistent"]
_MULTI_RUN_PATTERNS = [r"mean\s*[±+/-]\s*std", r"均值\s*[±]\s*标准差", r"±\s*[\d.]+", r"n[_-]?runs", r"n_repeats", r"重复.{0,6}\d+\s*次"]
_COMPARE_PATTERNS = [r"比\s*\S+", r"优于", r"超过", r"好于", r"强于", r"outperform", r"better\s+than", r"superior"]
# 设备编号交集/无泄漏的直接证据
_NO_OVERLAP_PATTERNS = [r"无交集", r"不重叠", r"没有.{0,6}重叠", r"no\s+overlap", r"disjoint", r"未见.{0,6}设备"]
_OVERLAP_PATTERNS = [r"有交集", r"存在重叠", r"overlap", r"同时.{0,6}(出现|属于|进入)"]


def _match_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _fact_role(fact: ExtractedFact) -> MaterialRole | None:
    """通过 store 查事实所属材料的角色。"""
    store = data_store.get(fact.session_id)
    if store is None:
        return None
    doc = store.docs.get(fact.source.material_id)
    return doc.role if doc else None


def _fact_text(fact: ExtractedFact) -> str:
    """事实的可扫描文本:值 + 原文片段。

    反证检查需要扫描完整上下文(如"设备不重叠"可能只在原文片段中,
    不在提取出的结构化值里),避免漏掉关键信号。
    """
    return f"{fact.effective_value()} {fact.source.snippet}"


class ClaimGraphService:
    """主张—证据图服务:构建、查询、用户校准。"""

    # ---- 构建 ----

    def build_graph(self, session_id: str) -> ClaimGraph:
        """基于已确认事实,确定性构建主张—证据图。

        每次构建生成新图(替换旧图),因为事实确认状态可能已变化。
        用户对旧图的校准(纠正/拒绝)会按 (sub_claim_text, fact_id) 尝试保留。
        """
        store = data_store.require(session_id)
        session = store.session
        old_graph = store.claim_graph

        usable = store.usable_facts()
        graph = ClaimGraph(session_id=session_id, created_at=datetime.now().isoformat())

        # 1. 拆解子主张
        for claim in session.claims:
            graph.sub_claims.extend(self._decompose_claim(claim))

        # 2. 连边 + 3. 反证检查
        for sc in graph.sub_claims:
            edges = self._build_edges_for_sub_claim(sc, usable)
            graph.edges.extend(edges)
            check = self._counter_check_for_sub_claim(sc, usable)
            if check:
                graph.counter_checks.append(check)

        # 保留用户对旧图的校准(按子主张文本+事实ID匹配)
        if old_graph:
            self._preserve_calibration(old_graph, graph)

        store.claim_graph = graph
        data_store.persist(session_id)
        logger.info(
            "构建主张-证据图:会话 %s,子主张 %d,边 %d(支持 %d/矛盾 %d/未知 %d),反证检查 %d",
            session_id, len(graph.sub_claims), graph.active_edge_count(),
            graph.supports_count(), graph.contradicts_count(), graph.unknown_count(),
            len(graph.counter_checks),
        )
        return graph

    # ---- 查询 ----

    def get_graph(self, session_id: str) -> ClaimGraph | None:
        store = data_store.get(session_id)
        return store.claim_graph if store else None

    # ---- 用户校准 ----

    def confirm_edge(
        self,
        session_id: str,
        edge_id: str,
        action: str,
        corrected_relation: str | None = None,
    ) -> ClaimEvidenceEdge:
        """用户对边的裁决:confirm / correct / reject。"""
        store = data_store.require(session_id)
        graph = store.claim_graph
        if graph is None:
            raise KeyError("尚未构建主张-证据图,请先调用 build")
        edge = next((e for e in graph.edges if e.edge_id == edge_id), None)
        if edge is None:
            raise KeyError(f"边不存在:{edge_id}")

        if action == "confirm":
            edge.status = EdgeStatus.CONFIRMED
        elif action == "correct":
            edge.status = EdgeStatus.CORRECTED
            if corrected_relation in ("supports", "contradicts", "unknown"):
                edge.corrected_relation = EdgeRelation(corrected_relation)
        elif action == "reject":
            edge.status = EdgeStatus.REJECTED
        else:
            raise ValueError(f"未知操作:{action},应为 confirm/correct/reject")

        data_store.persist(session_id)
        return edge

    def confirm_sub_claim(
        self, session_id: str, sub_claim_id: str, action: str
    ) -> SubClaim:
        """用户对模型候选子主张的裁决:confirm / reject。"""
        store = data_store.require(session_id)
        graph = store.claim_graph
        if graph is None:
            raise KeyError("尚未构建主张-证据图")
        sc = graph.sub_claim_by_id(sub_claim_id)
        if sc is None:
            raise KeyError(f"子主张不存在:{sub_claim_id}")

        if action == "confirm":
            sc.status = EdgeStatus.CONFIRMED
        elif action == "reject":
            sc.status = EdgeStatus.REJECTED
            # 级联:拒绝子主张时,其下所有边一并拒绝
            for e in graph.edges:
                if e.sub_claim_id == sub_claim_id:
                    e.status = EdgeStatus.REJECTED
        else:
            raise ValueError(f"未知操作:{action},应为 confirm/reject")

        data_store.persist(session_id)
        return sc

    def add_candidates(
        self,
        session_id: str,
        candidate_sub_claims: list[SubClaim],
        candidate_edges: list[ClaimEvidenceEdge],
        candidate_checks: list[CounterEvidenceCheck] | None = None,
    ) -> ClaimGraph:
        """添加模型提出的候选子主张/边(status=pending,待用户确认)。"""
        store = data_store.require(session_id)
        graph = store.claim_graph
        if graph is None:
            raise KeyError("尚未构建主张-证据图,请先构建规则图再添加候选")

        existing_texts = {sc.text for sc in graph.sub_claims}
        for sc in candidate_sub_claims:
            if sc.text not in existing_texts:
                sc.source = EdgeSource.LLM
                sc.status = EdgeStatus.PENDING
                graph.sub_claims.append(sc)
                existing_texts.add(sc.text)

        existing_edge_keys = {(e.sub_claim_id, e.fact_id) for e in graph.edges}
        for e in candidate_edges:
            if (e.sub_claim_id, e.fact_id) not in existing_edge_keys:
                e.source = EdgeSource.LLM
                e.status = EdgeStatus.PENDING
                graph.edges.append(e)
                existing_edge_keys.add((e.sub_claim_id, e.fact_id))

        if candidate_checks:
            existing_check_scids = {cc.sub_claim_id for cc in graph.counter_checks}
            for cc in candidate_checks:
                if cc.sub_claim_id not in existing_check_scids:
                    graph.counter_checks.append(cc)
                    existing_check_scids.add(cc.sub_claim_id)

        data_store.persist(session_id)
        return graph

    # ---- 内部:拆解 ----

    def _decompose_claim(self, claim) -> list[SubClaim]:
        """按模式词把主张拆成可检验子主张。"""
        text = claim.text
        subs: list[SubClaim] = []
        keywords = claim.scope_keywords or []

        if _match_any(text, _NEW_ENTITY_PATTERNS):
            subs.append(SubClaim(
                claim_id=claim.claim_id,
                text="测试集由训练时未见过的设备/实体组成(无数据泄漏)",
                test_aspect=TestAspect.SCOPE,
                scope_keywords=keywords or ["新设备"],
            ))
        if _match_any(text, _COMPARE_PATTERNS):
            subs.append(SubClaim(
                claim_id=claim.claim_id,
                text="主方法在评价指标上优于所比较的基线",
                test_aspect=TestAspect.COMPARISON,
                scope_keywords=keywords,
            ))
            subs.append(SubClaim(
                claim_id=claim.claim_id,
                text="基线在相同数据划分与指标条件下评估(比较公平)",
                test_aspect=TestAspect.BASELINE_FAIRNESS,
                scope_keywords=keywords,
            ))
        if _match_any(text, _STABILITY_PATTERNS):
            subs.append(SubClaim(
                claim_id=claim.claim_id,
                text="该优势在多次运行中保持稳定(非单次偶然)",
                test_aspect=TestAspect.STABILITY,
                scope_keywords=keywords,
            ))
        # 每个主张都需要可核实的指标
        subs.append(SubClaim(
            claim_id=claim.claim_id,
            text="提供了可核实的评价指标数值",
            test_aspect=TestAspect.METRIC_AVAIL,
            scope_keywords=keywords,
        ))
        return subs

    # ---- 内部:连边 ----

    def _build_edges_for_sub_claim(
        self, sc: SubClaim, facts: list[ExtractedFact]
    ) -> list[ClaimEvidenceEdge]:
        """为子主张构建证据边。只绑定已验证事实(入参 facts 已经过 usable 过滤)。"""
        by_cat: dict[FactCategory, list[ExtractedFact]] = {}
        for f in facts:
            by_cat.setdefault(f.category, []).append(f)

        if sc.test_aspect == TestAspect.SCOPE:
            return self._edges_for_scope(sc, by_cat.get(FactCategory.DATA_SPLIT, []))
        if sc.test_aspect == TestAspect.COMPARISON:
            return self._edges_for_comparison(sc, by_cat)
        if sc.test_aspect == TestAspect.STABILITY:
            return self._edges_for_stability(sc, by_cat.get(FactCategory.REPETITION, []))
        if sc.test_aspect == TestAspect.BASELINE_FAIRNESS:
            return self._edges_for_baseline_fairness(sc, by_cat.get(FactCategory.BASELINE, []))
        if sc.test_aspect == TestAspect.METRIC_AVAIL:
            return self._edges_for_metric(sc, by_cat.get(FactCategory.METRIC, []))
        return []

    def _edges_for_scope(
        self, sc: SubClaim, split_facts: list[ExtractedFact]
    ) -> list[ClaimEvidenceEdge]:
        """scope 子主张:划分方式是否支持"未见实体"。"""
        edges: list[ClaimEvidenceEdge] = []
        if not split_facts:
            edges.append(ClaimEvidenceEdge(
                sub_claim_id=sc.sub_claim_id, fact_id=None,
                relation=EdgeRelation.UNKNOWN,
                basis="未提供任何数据划分信息,无法核实测试集是否由未见实体组成",
                direction=EvidenceDirection.MISSING_PREMISE,
                scope="、".join(sc.scope_keywords) if sc.scope_keywords else "",
            ))
            return edges

        for f in split_facts:
            val = f.effective_value()
            role = _fact_role(f)
            direction = EvidenceDirection.PLAN if role == MaterialRole.PLAN else EvidenceDirection.EXECUTION
            if _match_any(val, _GROUP_SPLIT_PATTERNS):
                edges.append(ClaimEvidenceEdge(
                    sub_claim_id=sc.sub_claim_id, fact_id=f.fact_id,
                    relation=EdgeRelation.SUPPORTS,
                    basis=f"{'计划' if role == MaterialRole.PLAN else '执行'}材料显示按设备/组划分,与'测试集为未见实体'一致",
                    direction=direction,
                ))
            elif _match_any(val, _RECORD_SPLIT_PATTERNS):
                edges.append(ClaimEvidenceEdge(
                    sub_claim_id=sc.sub_claim_id, fact_id=f.fact_id,
                    relation=EdgeRelation.CONTRADICTS,
                    basis=f"{'计划' if role == MaterialRole.PLAN else '执行'}材料显示按记录随机划分,同设备记录可能同时进入训练与测试集",
                    direction=direction,
                ))
        return edges

    def _edges_for_comparison(
        self, sc: SubClaim, by_cat: dict[FactCategory, list[ExtractedFact]]
    ) -> list[ClaimEvidenceEdge]:
        """comparison 子主张:是否有指标与基线支持比较结论。"""
        edges: list[ClaimEvidenceEdge] = []
        metric_facts = by_cat.get(FactCategory.METRIC, [])
        baseline_facts = by_cat.get(FactCategory.BASELINE, [])

        for f in metric_facts:
            edges.append(ClaimEvidenceEdge(
                sub_claim_id=sc.sub_claim_id, fact_id=f.fact_id,
                relation=EdgeRelation.SUPPORTS,
                basis="提供了评价指标数值,比较结论可被量化核实",
                direction=EvidenceDirection.RESULT,
            ))
        for f in baseline_facts:
            edges.append(ClaimEvidenceEdge(
                sub_claim_id=sc.sub_claim_id, fact_id=f.fact_id,
                relation=EdgeRelation.SUPPORTS,
                basis="材料中存在基线方法运行记录,存在比较对象",
                direction=EvidenceDirection.RESULT,
            ))
        if not metric_facts and not baseline_facts:
            edges.append(ClaimEvidenceEdge(
                sub_claim_id=sc.sub_claim_id, fact_id=None,
                relation=EdgeRelation.UNKNOWN,
                basis="未发现指标数值或基线记录,比较结论无法核实",
                direction=EvidenceDirection.MISSING_PREMISE,
            ))
        return edges

    def _edges_for_stability(
        self, sc: SubClaim, rep_facts: list[ExtractedFact]
    ) -> list[ClaimEvidenceEdge]:
        """stability 子主张:是否有多次运行波动数据。"""
        edges: list[ClaimEvidenceEdge] = []
        if not rep_facts:
            edges.append(ClaimEvidenceEdge(
                sub_claim_id=sc.sub_claim_id, fact_id=None,
                relation=EdgeRelation.UNKNOWN,
                basis="未提供任何重复运行或随机种子信息,稳定性无法核实",
                direction=EvidenceDirection.MISSING_PREMISE,
            ))
            return edges

        has_multi = any(_match_any(f.effective_value(), _MULTI_RUN_PATTERNS) for f in rep_facts)
        for f in rep_facts:
            val = f.effective_value()
            if _match_any(val, _MULTI_RUN_PATTERNS):
                edges.append(ClaimEvidenceEdge(
                    sub_claim_id=sc.sub_claim_id, fact_id=f.fact_id,
                    relation=EdgeRelation.SUPPORTS,
                    basis="发现多次运行的波动报告(均值±标准差),稳定性可被核实",
                    direction=EvidenceDirection.RESULT,
                ))
            elif has_multi:
                continue  # 已有更强证据,弱证据边不重复建
            elif "seed" in val.lower() or "random_state" in val.lower():
                edges.append(ClaimEvidenceEdge(
                    sub_claim_id=sc.sub_claim_id, fact_id=f.fact_id,
                    relation=EdgeRelation.CONTRADICTS,
                    basis="仅发现随机种子设置,未见多次运行波动报告,单次结果无法体现稳定性",
                    direction=EvidenceDirection.EXECUTION,
                ))
        return edges

    def _edges_for_baseline_fairness(
        self, sc: SubClaim, baseline_facts: list[ExtractedFact]
    ) -> list[ClaimEvidenceEdge]:
        """baseline_fairness 子主张:基线是否在同等条件下评估。"""
        edges: list[ClaimEvidenceEdge] = []
        if not baseline_facts:
            edges.append(ClaimEvidenceEdge(
                sub_claim_id=sc.sub_claim_id, fact_id=None,
                relation=EdgeRelation.UNKNOWN,
                basis="未发现基线方法运行记录,比较公平性无法核实",
                direction=EvidenceDirection.MISSING_PREMISE,
            ))
            return edges

        for f in baseline_facts:
            edges.append(ClaimEvidenceEdge(
                sub_claim_id=sc.sub_claim_id, fact_id=f.fact_id,
                relation=EdgeRelation.SUPPORTS,
                basis="存在基线运行记录;但是否与主方法使用相同划分与指标仍需核对",
                direction=EvidenceDirection.RESULT,
            ))
        return edges

    def _edges_for_metric(
        self, sc: SubClaim, metric_facts: list[ExtractedFact]
    ) -> list[ClaimEvidenceEdge]:
        """metric_avail 子主张:是否提供了评价指标。"""
        edges: list[ClaimEvidenceEdge] = []
        if not metric_facts:
            edges.append(ClaimEvidenceEdge(
                sub_claim_id=sc.sub_claim_id, fact_id=None,
                relation=EdgeRelation.UNKNOWN,
                basis="未发现任何评价指标,结论无法被量化核实",
                direction=EvidenceDirection.MISSING_PREMISE,
            ))
            return edges

        for f in metric_facts:
            edges.append(ClaimEvidenceEdge(
                sub_claim_id=sc.sub_claim_id, fact_id=f.fact_id,
                relation=EdgeRelation.SUPPORTS,
                basis="提供了评价指标,结论可被量化核实",
                direction=EvidenceDirection.RESULT,
            ))
        return edges

    # ---- 内部:反证检查 ----

    def _counter_check_for_sub_claim(
        self, sc: SubClaim, facts: list[ExtractedFact]
    ) -> CounterEvidenceCheck | None:
        """对子主张做反证与替代解释检查。"""
        by_cat: dict[FactCategory, list[ExtractedFact]] = {}
        for f in facts:
            by_cat.setdefault(f.category, []).append(f)

        if sc.test_aspect == TestAspect.SCOPE:
            return self._counter_for_scope(sc, by_cat)
        if sc.test_aspect == TestAspect.COMPARISON:
            return self._counter_for_comparison(sc, by_cat)
        if sc.test_aspect == TestAspect.STABILITY:
            return self._counter_for_stability(sc, by_cat.get(FactCategory.REPETITION, []))
        if sc.test_aspect == TestAspect.BASELINE_FAIRNESS:
            return self._counter_for_baseline_fairness(sc, by_cat.get(FactCategory.BASELINE, []))
        return None  # metric_avail 不需要反证检查

    def _counter_for_scope(
        self, sc: SubClaim, by_cat: dict[FactCategory, list[ExtractedFact]]
    ) -> CounterEvidenceCheck:
        """scope 反证:设备编号是否重叠(数据泄漏)。

        认识论区分:
        - 执行为记录级随机划分 → counter_exists(划分方式本身就是反证)
        - 有"无交集/不重叠"直接证据 → counter_refuted(反证被排除)
        - 划分为组级但无交集直接证据 → no_counter_found(没找到反证≠证明不存在)
        """
        split_facts = by_cat.get(FactCategory.DATA_SPLIT, [])
        ds_facts = by_cat.get(FactCategory.DATASET_DESC, [])
        all_text = " ".join(_fact_text(f) for f in split_facts + ds_facts)

        if _match_any(all_text, _OVERLAP_PATTERNS):
            return CounterEvidenceCheck(
                sub_claim_id=sc.sub_claim_id,
                alternative_explanation="训练集与测试集的设备编号存在重叠,测试集并非全由未见设备组成",
                proof_status=CounterProofStatus.COUNTER_EXISTS,
                basis="材料中出现了设备编号重叠/交集的记录,数据泄漏反证成立",
                fact_ids=[f.fact_id for f in split_facts + ds_facts],
                missing_to_prove_absence=[],
            )

        exec_splits = [f for f in split_facts if _fact_role(f) == MaterialRole.EXECUTION]
        exec_text = " ".join(_fact_text(f) for f in exec_splits)
        if _match_any(exec_text, _RECORD_SPLIT_PATTERNS) and not _match_any(exec_text, _GROUP_SPLIT_PATTERNS):
            return CounterEvidenceCheck(
                sub_claim_id=sc.sub_claim_id,
                alternative_explanation="执行为记录级随机划分,同设备记录可能同时进入训练与测试集(数据泄漏)",
                proof_status=CounterProofStatus.COUNTER_EXISTS,
                basis="记录级划分方式本身构成反证:无法保证测试集由未见设备组成",
                fact_ids=[f.fact_id for f in exec_splits],
                missing_to_prove_absence=[],
            )

        if _match_any(all_text, _NO_OVERLAP_PATTERNS):
            return CounterEvidenceCheck(
                sub_claim_id=sc.sub_claim_id,
                alternative_explanation="训练集与测试集的设备编号可能存在重叠(数据泄漏)",
                proof_status=CounterProofStatus.COUNTER_REFUTED,
                basis="材料提供了设备编号无交集/不重叠的直接证据,泄漏反证被排除",
                fact_ids=[f.fact_id for f in ds_facts if _match_any(f.effective_value(), _NO_OVERLAP_PATTERNS)],
                missing_to_prove_absence=[],
            )

        return CounterEvidenceCheck(
            sub_claim_id=sc.sub_claim_id,
            alternative_explanation="训练集与测试集的设备编号可能存在重叠(数据泄漏)",
            proof_status=CounterProofStatus.NO_COUNTER_FOUND,
            basis="在已有材料中未发现设备编号重叠的证据,但也未提供无交集的直接证明——不能排除泄漏",
            fact_ids=[f.fact_id for f in split_facts],
            missing_to_prove_absence=["训练集与测试集设备编号交集检查结果(用于把'没找到反证'升级为'证明不存在反证')"],
        )

    def _counter_for_comparison(
        self, sc: SubClaim, by_cat: dict[FactCategory, list[ExtractedFact]]
    ) -> CounterEvidenceCheck:
        """comparison 反证:指标差异可能来自评估条件不同。"""
        baseline_facts = by_cat.get(FactCategory.BASELINE, [])
        if not baseline_facts:
            return CounterEvidenceCheck(
                sub_claim_id=sc.sub_claim_id,
                alternative_explanation="指标差异可能来自评估条件不同(划分/指标/预处理),而非方法本身优劣",
                proof_status=CounterProofStatus.NO_COUNTER_FOUND,
                basis="未发现基线运行记录,无法检查评估条件是否一致,也不能排除条件差异解释",
                fact_ids=[],
                missing_to_prove_absence=["基线在相同划分与指标下的运行记录", "评估条件一致性说明"],
            )
        return CounterEvidenceCheck(
            sub_claim_id=sc.sub_claim_id,
            alternative_explanation="指标差异可能来自评估条件不同(划分/指标/预处理),而非方法本身优劣",
            proof_status=CounterProofStatus.NO_COUNTER_FOUND,
            basis="存在基线记录,但是否与主方法使用相同划分与指标尚无直接说明,条件差异解释未被排除",
            fact_ids=[f.fact_id for f in baseline_facts],
            missing_to_prove_absence=["基线与主方法评估条件一致的直接说明"],
        )

    def _counter_for_stability(
        self, sc: SubClaim, rep_facts: list[ExtractedFact]
    ) -> CounterEvidenceCheck:
        """stability 反证:单次运行的'稳定'可能只是偶然。"""
        if not rep_facts:
            return CounterEvidenceCheck(
                sub_claim_id=sc.sub_claim_id,
                alternative_explanation="单次运行的'稳定'可能只是偶然,换种子或换划分后优势可能消失",
                proof_status=CounterProofStatus.NO_COUNTER_FOUND,
                basis="未提供任何重复运行信息,偶然性反证既未找到也未被排除",
                fact_ids=[],
                missing_to_prove_absence=["多次运行(建议≥5次)的均值±标准差"],
            )

        has_multi = any(_match_any(f.effective_value(), _MULTI_RUN_PATTERNS) for f in rep_facts)
        if has_multi:
            return CounterEvidenceCheck(
                sub_claim_id=sc.sub_claim_id,
                alternative_explanation="单次运行的'稳定'可能只是偶然,换种子或换划分后优势可能消失",
                proof_status=CounterProofStatus.COUNTER_REFUTED,
                basis="提供了多次运行的波动数据(均值±标准差),偶然性反证被排除",
                fact_ids=[f.fact_id for f in rep_facts if _match_any(f.effective_value(), _MULTI_RUN_PATTERNS)],
                missing_to_prove_absence=[],
            )

        return CounterEvidenceCheck(
            sub_claim_id=sc.sub_claim_id,
            alternative_explanation="单次运行的'稳定'可能只是偶然,换种子或换划分后优势可能消失",
            proof_status=CounterProofStatus.COUNTER_EXISTS,
            basis="仅有单次运行(或仅设随机种子),无多次运行波动数据——单次结果本身就是对稳定性主张的反证",
            fact_ids=[f.fact_id for f in rep_facts],
            missing_to_prove_absence=["多次运行的均值±标准差(可消除此反证)"],
        )

    def _counter_for_baseline_fairness(
        self, sc: SubClaim, baseline_facts: list[ExtractedFact]
    ) -> CounterEvidenceCheck:
        """baseline_fairness 反证:基线可能在不同条件下评估。"""
        if not baseline_facts:
            return CounterEvidenceCheck(
                sub_claim_id=sc.sub_claim_id,
                alternative_explanation="基线可能在不同数据划分或指标下评估,比较不公平",
                proof_status=CounterProofStatus.NO_COUNTER_FOUND,
                basis="未发现基线记录,公平性反证无法检查",
                fact_ids=[],
                missing_to_prove_absence=["基线方法的运行配置", "基线在相同划分与指标下的结果"],
            )
        return CounterEvidenceCheck(
            sub_claim_id=sc.sub_claim_id,
            alternative_explanation="基线可能在不同数据划分或指标下评估,比较不公平",
            proof_status=CounterProofStatus.NO_COUNTER_FOUND,
            basis="存在基线记录,但其评估条件是否与主方法一致无直接说明,不公平反证未被排除",
            fact_ids=[f.fact_id for f in baseline_facts],
            missing_to_prove_absence=["基线评估条件与主方法一致的直接说明"],
        )

    # ---- 内部:校准保留 ----

    def _preserve_calibration(self, old: ClaimGraph, new: ClaimGraph) -> None:
        """重建图时,尽量保留用户对旧图的校准(纠正/拒绝)。

        匹配键:子主张文本 + 事实ID。文本相同视为同一子主张。
        """
        old_sc_by_text = {sc.text: sc for sc in old.sub_claims}
        old_edge_by_key = {(e.sub_claim_id, e.fact_id): e for e in old.edges}
        # 旧子主张ID -> 新子主张ID 的映射(按文本匹配)
        id_map: dict[str, str] = {}
        for sc in new.sub_claims:
            old_sc = old_sc_by_text.get(sc.text)
            if old_sc:
                id_map[old_sc.sub_claim_id] = sc.sub_claim_id
                if old_sc.source == EdgeSource.LLM and old_sc.status != EdgeStatus.PENDING:
                    sc.status = old_sc.status

        for e in new.edges:
            new_sc_id = e.sub_claim_id
            # 找旧图中同子主张文本+同事实的边
            for old_sc_text, old_sc in old_sc_by_text.items():
                if id_map.get(old_sc.sub_claim_id) == new_sc_id:
                    old_e = old_edge_by_key.get((old_sc.sub_claim_id, e.fact_id))
                    if old_e and old_e.status in (EdgeStatus.CORRECTED, EdgeStatus.REJECTED):
                        e.status = old_e.status
                        e.corrected_relation = old_e.corrected_relation
                    break


claim_graph_service = ClaimGraphService()