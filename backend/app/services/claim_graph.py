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
from app.services.evidence_checks import entity_overlap

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
        graph = ClaimGraph(session_id=session_id, rule_version=3, created_at=datetime.now().isoformat())

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
        if store and store.claim_graph and store.claim_graph.rule_version < 3:
            return self.build_graph(session_id)
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
                text="所提供训练/测试实体编号列表无交集（仍需核对来源与其他泄漏途径）",
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

    def _edges_for_scope(self, sc: SubClaim, split_facts: list[ExtractedFact]) -> list[ClaimEvidenceEdge]:
        edges = []
        for f in split_facts:
            store = data_store.get(f.session_id)
            overlap = entity_overlap(f, store.docs) if store else None
            relation = EdgeRelation.UNKNOWN
            basis = "存在划分相关材料；函数名称或分组计划不能证明实际实体是否重叠，需提供训练/测试实体编号。"
            if overlap is not None:
                relation = EdgeRelation.CONTRADICTS if overlap else EdgeRelation.SUPPORTS
                basis = ("提供的实体列表存在交集：" + ", ".join(sorted(overlap)[:10]) if overlap else
                         "提供的训练/测试实体编号列表无交集；仅支持这些列表的实体隔离，不验证列表来源、完整性或其他泄漏。")
            edges.append(ClaimEvidenceEdge(
                sub_claim_id=sc.sub_claim_id, fact_id=f.fact_id, relation=relation,
                basis=basis, direction=(EvidenceDirection.PLAN if _fact_role(f) == MaterialRole.PLAN else EvidenceDirection.EXECUTION),
            ))
        return edges or [ClaimEvidenceEdge(sub_claim_id=sc.sub_claim_id, fact_id=None,
            relation=EdgeRelation.UNKNOWN, basis="缺少实际划分与实体编号记录。", direction=EvidenceDirection.MISSING_PREMISE)]

    def _edges_for_comparison(self, sc: SubClaim, by_cat: dict[FactCategory, list[ExtractedFact]]) -> list[ClaimEvidenceEdge]:
        facts = by_cat.get(FactCategory.METRIC, []) + by_cat.get(FactCategory.BASELINE, [])
        return self._observation_edges(sc, facts, "comparison",
            "仅发现相关材料；需完整的方法、指标方向、双方数值与相同测试条件，才能核对限定表中的比较。")

    def _observation_edges(self, sc, facts, aspect, fallback):
        from app.services.numeric_evidence import evaluate_fact
        edges = []
        for fact in facts:
            store = data_store.require(fact.session_id)
            claim = next((c.text for c in store.session.claims if c.claim_id == sc.claim_id), "")
            result = evaluate_fact(fact, store.docs, aspect, claim)
            if result is None:
                edges.extend(self._related_edges(sc, [fact], fallback))
            else:
                relation, basis = result
                edges.append(ClaimEvidenceEdge(sub_claim_id=sc.sub_claim_id, fact_id=fact.fact_id,
                    relation=EdgeRelation(relation), basis=basis, direction=EvidenceDirection.RESULT))
        return edges or self._related_edges(sc, [], fallback)

    @staticmethod
    def _related_edges(sc, facts, basis):
        return [ClaimEvidenceEdge(
            sub_claim_id=sc.sub_claim_id, fact_id=f.fact_id, relation=EdgeRelation.UNKNOWN,
            basis=basis + (" 此项来自计划，尚非执行结果。" if _fact_role(f) == MaterialRole.PLAN else ""),
            direction=(EvidenceDirection.PLAN if _fact_role(f) == MaterialRole.PLAN else EvidenceDirection.EXECUTION),
        ) for f in facts] or [ClaimEvidenceEdge(
            sub_claim_id=sc.sub_claim_id, fact_id=None, relation=EdgeRelation.UNKNOWN,
            basis="未提供相关证据，无法核实。", direction=EvidenceDirection.MISSING_PREMISE,
        )]

    def _edges_for_stability(self, sc: SubClaim, rep_facts: list[ExtractedFact]) -> list[ClaimEvidenceEdge]:
        return self._observation_edges(sc, rep_facts, "stability",
            "重复次数、种子或单项波动仅为线索；需明确双方同条件样本标准差和有限运行范围，才能作样本内比较。")

    def _edges_for_baseline_fairness(self, sc: SubClaim, baseline_facts: list[ExtractedFact]) -> list[ClaimEvidenceEdge]:
        return self._related_edges(sc, baseline_facts, "存在基线相关材料；尚未核对划分、指标、预处理与预算是否一致，比较公平性待核实。")

    def _edges_for_metric(self, sc: SubClaim, metric_facts: list[ExtractedFact]) -> list[ClaimEvidenceEdge]:
        return self._related_edges(sc, metric_facts, "提及评价指标；指标名称本身不能替代计算定义与实际数值，完整性待核实。")

    # ---- 反证与替代解释 ----

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

    def _counter_for_scope(self, sc: SubClaim, by_cat: dict[FactCategory, list[ExtractedFact]]) -> CounterEvidenceCheck:
        facts = by_cat.get(FactCategory.DATA_SPLIT, [])
        checked = [(f, entity_overlap(f, data_store.require(f.session_id).docs)) for f in facts]
        overlaps = [(f, overlap) for f, overlap in checked if overlap]
        disjoint = [(f, overlap) for f, overlap in checked if overlap is not None and not overlap]
        status = CounterProofStatus.COUNTER_EXISTS if overlaps else CounterProofStatus.NO_COUNTER_FOUND
        return CounterEvidenceCheck(
            sub_claim_id=sc.sub_claim_id, alternative_explanation="训练/测试实体可能重叠，削弱未见实体泛化的论证",
            proof_status=status,
            basis=("提供的实体列表检出交集。" if overlaps else
                   "提供的实体列表无交集；尚未验证列表来源、完整性与其他泄漏途径。" if disjoint else
                   "函数名、分组说明或无交集口头声明均不足以核实实际实体隔离。"),
            fact_ids=[f.fact_id for f in facts],
            missing_to_prove_absence=["完整训练/测试实体编号与可复查的划分日志"],
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

    def _counter_for_stability(self, sc: SubClaim, rep_facts: list[ExtractedFact]) -> CounterEvidenceCheck:
        return CounterEvidenceCheck(
            sub_claim_id=sc.sub_claim_id,
            alternative_explanation="观测到的优势可能来自运行波动或评价条件差异",
            proof_status=CounterProofStatus.NO_COUNTER_FOUND,
            basis="单次运行不能证明不稳定；多次运行也不能自动排除偶然性。尚需核对原始重复结果、比较条件与不确定性。",
            fact_ids=[f.fact_id for f in rep_facts],
            missing_to_prove_absence=["各方法相同条件下的重复结果、波动与不确定性分析"],
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
