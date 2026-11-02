"""智能体核心服务。

四项核心能力(每项都有"模型优先 + 启发式降级"双模式):

1. analyze_direction  科研方向审查:理解主张,判断实验设计关键要求
2. analyze_gaps       材料缺口分析:判断当前材料是否足以审查,还缺什么
3. generate_followups 自主追问:针对"信息不足"生成针对性追问
4. deep_review        模型复核:处理规则无法覆盖的复杂上下文(引用校验)
5. generate_teaching_case 教学案例:复查后训练实验设计能力

无 LLM 密钥时,所有能力降级到启发式规则:
- 基于已提取事实的简单推理
- 基于规则发现的结构化追问
- 预设教学案例库
明确告知用户"接入模型可获得更深入分析"。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.agent import prompts
from app.agent.llm_client import llm_client
from app.models.claim import ExperimentType, ReviewSession
from app.models.evidence import ExtractedFact, MaterialRole, ParsedDocument
from app.models.review import Finding, FindingLevel, ReviewReport
from app.services.store import SessionStore, data_store

logger = logging.getLogger("agent")


# ---- 智能体输出数据结构 ----

@dataclass
class DirectionAnalysis:
    """科研方向审查结果。"""
    claim_clarity: str = "unknown"  # clear / vague / untestable / unknown
    clarity_note: str = ""
    design_requirements: list[dict] = field(default_factory=list)
    direction_issues: list[dict] = field(default_factory=list)
    source: str = "heuristic"  # heuristic / llm


@dataclass
class GapAnalysis:
    """材料缺口分析结果。"""
    sufficiency: str = "unknown"  # sufficient / partial / insufficient / unknown
    gaps: list[dict] = field(default_factory=list)
    summary: str = ""
    source: str = "heuristic"


@dataclass
class Followup:
    """自主追问。"""
    target_finding: str = ""
    question: str = ""
    what_to_provide: str = ""
    why_needed: str = ""


@dataclass
class DeepFinding:
    """模型复核发现(引用已校验)。"""
    level: str = "insufficient"
    title: str = ""
    reasoning: str = ""
    verified_quote: str = ""
    material_filename: str = ""
    suggestion: str = ""
    suggestion_type: str = "clarify"
    quote_verified: bool = False
    # 详细建议三部分(结构化,前端分行展示)
    suggestion_action: str = ""   # 具体怎么改
    suggestion_reason: str = ""   # 为什么这样改
    suggestion_verify: str = ""   # 如何验证


@dataclass
class MaterialCoverage:
    """单份材料的复核覆盖情况(透明度:告知用户模型实际检查了哪些范围)。"""
    material_id: str = ""
    filename: str = ""
    role: str = ""           # plan / execution
    total_chars: int = 0     # 材料全文长度
    checked_chars: int = 0   # 模型实际检查的字符数
    truncated: bool = False  # 是否有内容未送入模型


@dataclass
class DeepReviewResult:
    """模型复核结果(含状态与覆盖范围,前端据此区分展示)。

    status 取值:
        ok               调用成功且有发现
        ok_no_findings   调用成功且无发现
        llm_unavailable  未配置大模型密钥
        llm_call_failed  模型调用失败(超时/网络)
        llm_parse_failed 模型返回了但解析失败
    """
    status: str = "ok"
    message: str = ""
    findings: list[DeepFinding] = field(default_factory=list)
    coverage: list[MaterialCoverage] = field(default_factory=list)
    llm_available: bool = False


@dataclass
class TeachingCase:
    """教学小案例。"""
    case_title: str = ""
    case_description: str = ""
    question: str = ""
    hint: str = ""
    reference_answer: str = ""
    related_rule: str = ""
    source: str = "preset"


class AgentService:
    """智能体服务:方向审查、缺口分析、自主追问、模型复核、教学案例。"""

    # ---- 1. 科研方向审查 ----

    def analyze_direction(self, session_id: str) -> DirectionAnalysis:
        """理解主张,判断实验设计关键要求。模型优先,启发式降级。"""
        store = data_store.require(session_id)
        session = store.session
        claims_text = "\n".join(f"- {c.text}" for c in session.claims)
        exp_label = "数据与模型实验" if session.experiment_type == ExperimentType.DATA_MODEL else "算法与系统性能实验"

        if llm_client.is_available():
            raw = llm_client.chat(
                prompts.DIRECTION_SYSTEM,
                prompts.DIRECTION_USER.format(claims=claims_text, experiment_type=exp_label),
            )
            data = llm_client.parse_json_response(raw)
            if isinstance(data, dict):
                return DirectionAnalysis(
                    claim_clarity=data.get("claim_clarity", "unknown"),
                    clarity_note=data.get("clarity_note", ""),
                    design_requirements=data.get("design_requirements", []),
                    direction_issues=data.get("direction_issues", []),
                    source="llm",
                )

        return self._heuristic_direction(session, claims_text)

    @staticmethod
    def _heuristic_direction(session: ReviewSession, claims_text: str) -> DirectionAnalysis:
        """启发式方向审查:基于关键词推断实验设计关键要求。"""
        requirements: list[dict] = []
        issues: list[dict] = []
        clarity = "clear"

        text = claims_text
        # 推断关键要求
        if any(kw in text for kw in ("新设备", "新机器", "未见", "unseen", "新用户", "新病人")):
            requirements.append({
                "requirement": "测试集必须由训练时未见过的设备/实体组成(按组划分,非记录级随机)",
                "reason": "主张涉及泛化到新实体,记录级随机划分会导致同一实体数据泄漏到测试集",
                "linked_claim_keyword": "新设备/未见",
            })
        if any(kw in text for kw in ("更稳定", "稳定", "鲁棒", "robust")):
            requirements.append({
                "requirement": "需要多次运行的波动数据(均值±标准差),而非单次结果",
                "reason": "稳定性主张需要多次重复运行才能体现",
                "linked_claim_keyword": "更稳定",
            })
        if any(kw in text for kw in ("比", "优于", "超过", "好于", "强于", "outperform", "better")):
            requirements.append({
                "requirement": "需要基线方法在相同数据划分与指标下的对比结果",
                "reason": "比较主张需要同等条件下的基线结果才能支持",
                "linked_claim_keyword": "比/优于",
            })
        if not requirements:
            clarity = "vague"
            issues.append({
                "issue": "主张未包含可检验的比较、泛化或稳定性表述,难以确定实验设计要求",
                "severity": "medium",
                "explanation": "建议明确主张的比较对象、适用范围和评价维度",
            })

        return DirectionAnalysis(
            claim_clarity=clarity,
            clarity_note="启发式分析:基于主张关键词推断实验设计要求。接入模型可获得更深入分析。",
            design_requirements=requirements,
            direction_issues=issues,
            source="heuristic",
        )

    # ---- 2. 材料缺口分析 ----

    def analyze_gaps(self, session_id: str) -> GapAnalysis:
        """判断当前材料是否足以审查,还缺什么。模型优先,启发式降级。"""
        store = data_store.require(session_id)
        session = store.session
        claims_text = "\n".join(f"- {c.text}" for c in session.claims)

        materials_desc = self._describe_materials(store)
        facts_desc = self._describe_facts(store)

        if llm_client.is_available():
            raw = llm_client.chat(
                prompts.GAP_SYSTEM,
                prompts.GAP_USER.format(
                    claims=claims_text, materials=materials_desc, facts=facts_desc
                ),
            )
            data = llm_client.parse_json_response(raw)
            if isinstance(data, dict):
                return GapAnalysis(
                    sufficiency=data.get("sufficiency", "unknown"),
                    gaps=data.get("gaps", []),
                    summary=data.get("summary", ""),
                    source="llm",
                )

        return self._heuristic_gaps(store, session)

    @staticmethod
    def _heuristic_gaps(store: SessionStore, session: ReviewSession) -> GapAnalysis:
        """启发式缺口分析:基于材料角色与事实类别推断缺口。"""
        gaps: list[dict] = []
        has_plan = any(d.role == MaterialRole.PLAN for d in store.docs.values())
        has_exec = any(d.role == MaterialRole.EXECUTION for d in store.docs.values())
        usable = store.usable_facts()
        categories = {f.category.value for f in usable}

        if not has_plan:
            gaps.append({
                "missing": "实验计划材料",
                "priority": "high",
                "reason": "没有计划,无法核对计划与执行的一致性",
                "how_to_provide": "上传或粘贴实验计划文档,标记为'计划'",
            })
        if not has_exec:
            gaps.append({
                "missing": "实际执行材料(代码/配置/结果)",
                "priority": "high",
                "reason": "没有执行材料,无法核实主张是否被实际实验支持",
                "how_to_provide": "上传代码、配置或运行结果,标记为'执行'",
            })
        if has_plan and has_exec and "data_split" not in categories:
            gaps.append({
                "missing": "数据划分方式说明",
                "priority": "high",
                "reason": "无法核实测试集构成,泛化类主张无法审查",
                "how_to_provide": "在计划或代码中明确数据如何划分",
            })
        if "metric" not in categories:
            gaps.append({
                "missing": "评价指标",
                "priority": "medium",
                "reason": "没有指标,任何'更好/更差'的结论都无法核实",
                "how_to_provide": "明确评价指标(如 F1、AUC、RMSE)及数值",
            })

        sufficiency = "sufficient" if not gaps else ("partial" if has_plan or has_exec else "insufficient")
        summary = f"启发式分析:已上传 {len(store.docs)} 份材料,发现 {len(gaps)} 个缺口。接入模型可获得更深入分析。"
        return GapAnalysis(sufficiency=sufficiency, gaps=gaps, summary=summary, source="heuristic")

    # ---- 3. 自主追问 ----

    def generate_followups(self, session_id: str) -> list[Followup]:
        """针对'信息不足'的发现生成追问。模型优先,启发式降级。"""
        store = data_store.require(session_id)
        report = store.latest_report()
        if report is None:
            return []

        insufficient = [f for f in report.findings if f.level == FindingLevel.INSUFFICIENT]
        if not insufficient:
            return []

        claims_text = "\n".join(f"- {c.text}" for c in store.session.claims)
        findings_desc = "\n".join(
            f"- 标题:{f.title}\n  缺什么:{'; '.join(f.missing_evidence)}\n  建议:{f.suggestion}"
            for f in insufficient
        )

        if llm_client.is_available():
            raw = llm_client.chat(
                prompts.FOLLOWUP_SYSTEM,
                prompts.FOLLOWUP_USER.format(
                    insufficient_findings=findings_desc, claims=claims_text
                ),
            )
            data = llm_client.parse_json_response(raw)
            if isinstance(data, dict) and isinstance(data.get("followups"), list):
                return [
                    Followup(
                        target_finding=item.get("target_finding", ""),
                        question=item.get("question", ""),
                        what_to_provide=item.get("what_to_provide", ""),
                        why_needed=item.get("why_needed", ""),
                    )
                    for item in data["followups"]
                    if isinstance(item, dict)
                ]

        # 启发式降级:直接把 missing_evidence 转成追问
        return [
            Followup(
                target_finding=f.title,
                question=f"请补充:{'; '.join(f.missing_evidence)}",
                what_to_provide="; ".join(f.missing_evidence),
                why_needed=f.reasoning,
            )
            for f in insufficient
        ]

    # ---- 3b. 基于预期信息价值的主动追问(P1) ----

    def generate_ranked_followups(self, session_id: str) -> dict:
        """生成 EIV 排序的主动追问:回答哪个问题最可能改变审查结论。

        流程:
        1. 取审查报告全部发现(按严重度排序)与主张-证据图的子主张。
        2. LLM 生成追问候选(含证据类型/格式/子主张绑定/评分因子)。
        3. followup_service 计算可解释 EIV 评分并排序。
        4. 保存追问列表,返回给前端展示"为何先问这个"。

        Returns:
            {status, message, questions, source}
        """
        from app.services.followup import followup_service

        store = data_store.require(session_id)
        report = store.latest_report()
        if report is None or not report.findings:
            return {"status": "no_findings", "message": "尚无审查发现,无需追问", "questions": [], "source": "none"}

        # 发现按严重度排序:contradiction > risk > insufficient
        level_order = {FindingLevel.CONTRADICTION: 0, FindingLevel.RISK: 1, FindingLevel.INSUFFICIENT: 2}
        sorted_findings = sorted(report.findings, key=lambda f: level_order.get(f.level, 9))
        findings_desc = "\n".join(
            f"- ID:{f.finding_id} 级别:{f.level.value} 标题:{f.title}\n"
            f"  缺什么:{'; '.join(f.missing_evidence) or '(无)'}\n"
            f"  建议:{f.suggestion}"
            for f in sorted_findings
        )
        claims_text = "\n".join(f"- {c.text}" for c in store.session.claims)

        # 子主张列表(若有主张-证据图)
        sub_claims_text = "(尚未构建主张-证据图)"
        if store.claim_graph and store.claim_graph.sub_claims:
            sub_claims_text = "\n".join(
                f"- ID:{sc.sub_claim_id} [{sc.test_aspect.value}] {sc.text}"
                for sc in store.claim_graph.sub_claims
            )

        raw_questions: list[dict] = []

        if llm_client.is_available():
            raw = llm_client.chat(
                prompts.FOLLOWUP_EIV_SYSTEM,
                prompts.FOLLOWUP_EIV_USER.format(
                    findings=findings_desc,
                    claims=claims_text,
                    sub_claims=sub_claims_text,
                ),
                retries=1,
            )
            if raw:
                data = llm_client.parse_json_response(raw)
                if isinstance(data, dict) and isinstance(data.get("followups"), list):
                    raw_questions = [i for i in data["followups"] if isinstance(i, dict)]

        if not raw_questions:
            # 启发式降级:从发现生成追问,按严重度赋因子
            for f in sorted_findings:
                cost = "low" if f.level == FindingLevel.INSUFFICIENT else "medium"
                raw_questions.append({
                    "target_finding_id": f.finding_id,
                    "target_finding_title": f.title,
                    "sub_claim_id": "",
                    "question": f"请补充:{'; '.join(f.missing_evidence) or f.suggestion}",
                    "what_to_provide": "; ".join(f.missing_evidence) or f.suggestion,
                    "why_needed": f.reasoning,
                    "evidence_type": "explanation",
                    "evidence_format": "文字说明或截图",
                    "uncertainty": 0.6 if f.level != FindingLevel.INSUFFICIENT else 0.4,
                    "change_probability": 0.7 if f.level == FindingLevel.CONTRADICTION else 0.5,
                    "answer_cost": cost,
                })

        questions = followup_service.generate_from_findings(session_id, raw_questions)
        followup_service.save_questions(session_id, questions)

        source = "llm" if llm_client.is_available() else "heuristic"
        return {
            "status": "ok",
            "message": f"已生成 {len(questions)} 条追问,按预期信息价值排序",
            "questions": questions,
            "source": source,
        }

    # ---- 4. 模型复核(复杂上下文,引用校验) ----

    def deep_review(self, session_id: str) -> DeepReviewResult:
        """模型复核:处理规则无法覆盖的复杂上下文。引用必须逐字校验。

        返回 DeepReviewResult,通过 status 区分:
        调用成功(有/无发现)、未接入模型、调用失败、解析失败。
        coverage 记录每份材料的实际检查范围(长文档截断时明示)。
        """
        store = data_store.require(session_id)
        session = store.session

        if not llm_client.is_available():
            return DeepReviewResult(
                status="llm_unavailable",
                message="未配置大模型密钥,模型复核不可用。配置 LLM_API_KEY 后可获得深入分析。",
                llm_available=False,
            )

        report = store.latest_report()
        existing = ""
        if report:
            existing = "\n".join(f"- [{f.level.value}] {f.title}" for f in report.findings)

        # 拼接材料内容(限制总长度防超 token),同时记录覆盖范围
        materials_text, coverage = self._materials_text(store, max_chars=8000)
        claims_text = "\n".join(f"- {c.text}" for c in session.claims)

        raw = llm_client.chat(
            prompts.DEEP_REVIEW_SYSTEM,
            prompts.DEEP_REVIEW_USER.format(
                claims=claims_text,
                materials_text=materials_text,
                existing_findings=existing or "(无)",
            ),
            max_tokens=3000,
            timeout=45,
            retries=1,
        )
        if raw is None:
            return DeepReviewResult(
                status="llm_call_failed",
                message="模型调用失败(超时或网络异常),请稍后重试。",
                coverage=coverage,
                llm_available=True,
            )

        data = llm_client.parse_json_response(raw)
        if not isinstance(data, dict) or not isinstance(data.get("deep_findings"), list):
            logger.warning(
                "模型复核输出解析失败,原始输出前200字符:%s", (raw or "")[:200]
            )
            return DeepReviewResult(
                status="llm_parse_failed",
                message="模型返回内容无法解析为结构化结果,请重试。",
                coverage=coverage,
                llm_available=True,
            )

        findings = self._parse_deep_findings(store, data["deep_findings"])
        return DeepReviewResult(
            status="ok" if findings else "ok_no_findings",
            message="" if findings else "模型已完成复核,未发现需要补充的问题。",
            findings=findings,
            coverage=coverage,
            llm_available=True,
        )

    def _parse_deep_findings(
        self, store: SessionStore, items: list
    ) -> list[DeepFinding]:
        """解析模型复核输出列表:结构化建议兼容、引用逐字校验。"""
        results: list[DeepFinding] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            action = item.get("suggestion_action", "")
            reason = item.get("suggestion_reason", "")
            verify = item.get("suggestion_verify", "")
            raw_suggestion = item.get("suggestion", "")
            # 兼容:模型未输出结构化字段时,用一句话建议补位
            if not action and raw_suggestion:
                action = raw_suggestion
            # 拼接结构化建议为多行文本(兼容旧字段/导出)
            parts = []
            if action:
                parts.append(f"具体怎么改:{action}")
            if reason:
                parts.append(f"为什么:{reason}")
            if verify:
                parts.append(f"如何验证:{verify}")
            suggestion = "\n".join(parts) or raw_suggestion
            finding = DeepFinding(
                level=item.get("level", "insufficient"),
                title=item.get("title", ""),
                reasoning=item.get("reasoning", ""),
                verified_quote=item.get("quote", ""),
                material_filename=item.get("material_filename", ""),
                suggestion=suggestion,
                suggestion_type=item.get("suggestion_type", "clarify"),
                suggestion_action=action,
                suggestion_reason=reason,
                suggestion_verify=verify,
            )
            # 引用校验:quote 必须在某份材料中逐字找到
            matching = [d for d in store.docs.values() if d.filename == finding.material_filename
                        and finding.verified_quote and len(finding.verified_quote) >= 4
                        and finding.verified_quote in d.content]
            finding.quote_verified = len(matching) == 1
            if not finding.quote_verified:
                logger.warning("模型复核缺少可绑定到指定文件的引用，降为待核实建议:%s", finding.title)
                finding.verified_quote = ""
                finding.material_filename = ""
                finding.level = "insufficient"
                finding.reasoning = "引用未通过指定文件校验，以下仅为待核实的模型建议。" + finding.reasoning
            results.append(finding)
        return results

    @staticmethod
    def _verify_quote(store: SessionStore, quote: str) -> bool:
        """校验 quote 是否在某份材料中逐字存在。"""
        if not quote or len(quote) < 4:
            return False
        for doc in store.docs.values():
            if quote in doc.content:
                return True
        return False

    # ---- 5. 教学案例 ----

    def generate_teaching_case(self, session_id: str) -> TeachingCase:
        """复查后生成教学小案例。模型优先,预设案例库降级。"""
        store = data_store.require(session_id)
        session = store.session
        report = store.latest_report()

        findings_summary = "无发现" if report is None else "\n".join(
            f"- [{f.level.value}] {f.title}" for f in report.findings
        )
        claims_text = "\n".join(f"- {c.text}" for c in session.claims)
        exp_label = session.experiment_type.value

        if llm_client.is_available():
            raw = llm_client.chat(
                prompts.TEACHING_SYSTEM,
                prompts.TEACHING_USER.format(
                    experiment_type=exp_label,
                    claims=claims_text,
                    findings_summary=findings_summary,
                ),
                temperature=0.7,
            )
            data = llm_client.parse_json_response(raw)
            if isinstance(data, dict) and data.get("case_description"):
                return TeachingCase(
                    case_title=data.get("case_title", ""),
                    case_description=data.get("case_description", ""),
                    question=data.get("question", ""),
                    hint=data.get("hint", ""),
                    reference_answer=data.get("reference_answer", ""),
                    related_rule=data.get("related_rule", ""),
                    source="llm",
                )

        return self._preset_teaching_case(session, report)

    @staticmethod
    def _preset_teaching_case(session: ReviewSession, report: ReviewReport | None) -> TeachingCase:
        """预设教学案例库(无模型时的降级)。根据触发过的规则选案例。"""
        triggered = {f.rule_id for f in (report.findings if report else [])}

        if "dm_claim_generalization" in triggered or "dm_split_consistency" in triggered:
            return TeachingCase(
                case_title="用户行为预测的划分问题",
                case_description=(
                    "小明研究用户流失预测模型,主张'模型能预测新用户的流失'。"
                    "他收集了 5000 名用户的行为数据,用 train_test_split(test_size=0.2)划分后训练,"
                    "测试集 F1 达到 0.92,于是得出结论。"
                ),
                question="小明的实验能支持他的结论吗?问题出在哪里?",
                hint="注意他的主张是'新用户',再看看他的划分方式。",
                reference_answer=(
                    "漏洞:主张是预测'新用户',但 train_test_split 是记录级随机划分,"
                    "同一用户的行为记录会同时出现在训练集和测试集中(数据泄漏),"
                    "模型可能只是记住了已知用户的行为模式,而非学会了预测新用户。"
                    "修改:应按用户 ID 分组划分(GroupShuffleSplit),确保测试集只含训练时未见过的用户。"
                ),
                related_rule="dm_claim_generalization",
                source="preset",
            )
        if "dm_repetition" in triggered:
            return TeachingCase(
                case_title="单次运行的稳定性结论",
                case_description=(
                    "小红对比两个推荐算法,主张'算法 X 比算法 Y 更稳定'。"
                    "她各运行了一次实验,算法 X 的 NDCG 为 0.85,算法 Y 为 0.83,得出结论。"
                ),
                question="小红的实验能支持'更稳定'的结论吗?",
                hint="'稳定'意味着什么?单次运行能体现吗?",
                reference_answer=(
                    "漏洞:'更稳定'需要多次运行的波动数据支持(均值±标准差),"
                    "单次运行只能说明这一次 X 略好,无法体现稳定性。"
                    "修改:各运行多次(建议≥5次),报告均值±标准差,比较波动大小。"
                ),
                related_rule="dm_repetition",
                source="preset",
            )
        return TeachingCase(
            case_title="基线缺失的比较",
            case_description=(
                "小刚提出了新的文本分类模型,主张'新模型优于现有方法'。"
                "他只运行了新模型,准确率 91%,没有运行任何基线方法,得出结论。"
            ),
            question="小刚的实验能支持'优于现有方法'的结论吗?",
            hint="比较需要什么?",
            reference_answer=(
                "漏洞:没有基线方法在相同数据与指标下的结果,'优于'无从谈起。"
                "修改:选择至少一个代表性基线,在相同数据划分与指标下运行对比。"
            ),
            related_rule="dm_baseline",
            source="preset",
        )

    # ---- 工具方法 ----

    @staticmethod
    def _describe_materials(store: SessionStore) -> str:
        lines = []
        for d in store.docs.values():
            role = "计划" if d.role == MaterialRole.PLAN else "执行"
            ocr = "(需OCR,内容不完整)" if d.ocr_required else ""
            lines.append(f"- [{role}] {d.filename} ({len(d.content)}字符){ocr}")
        return "\n".join(lines) or "(无)"

    @staticmethod
    def _describe_facts(store: SessionStore) -> str:
        usable = store.usable_facts()
        if not usable:
            return "(无已确认事实)"
        lines = []
        for f in usable:
            lines.append(f"- [{f.category.value}] {f.effective_value()}")
        return "\n".join(lines)

    @staticmethod
    def _materials_text(
        store: SessionStore, max_chars: int = 8000, per_doc_limit: int = 2000
    ) -> tuple[str, list[MaterialCoverage]]:
        """拼接材料内容供模型复核,同时记录每份材料的实际检查范围。

        限制:单份材料最多 per_doc_limit 字符,总量最多 max_chars 字符。
        超出部分不送入模型,但在 coverage 中标记 truncated=True,
        前端明确告知用户哪些内容未检查,避免误以为已全量复核。
        """
        parts: list[str] = []
        coverage: list[MaterialCoverage] = []
        total = 0
        for d in store.docs.values():
            role = "plan" if d.role == MaterialRole.PLAN else "execution"
            total_chars = len(d.content)
            doc_take = min(total_chars, per_doc_limit)
            if doc_take > 0 and total + doc_take <= max_chars:
                content = d.content[:per_doc_limit]
                total += len(content)
                header = f"=== [{role}] {d.filename} ==="
                # 截断标注:告知模型该材料不完整,避免对未见内容误判"未发现问题"
                tail = (
                    f"\n[注意:该材料共 {total_chars} 字符,此处仅提供前 {per_doc_limit} 字符,"
                    f"后续内容未提供。若问题可能在未提供部分,请在 reasoning 中说明无法完整判断。]"
                    if total_chars > per_doc_limit
                    else ""
                )
                parts.append(f"{header}\n{content}{tail}")
                coverage.append(MaterialCoverage(
                    material_id=d.material_id,
                    filename=d.filename,
                    role=role,
                    total_chars=total_chars,
                    checked_chars=len(content),
                    truncated=total_chars > per_doc_limit,
                ))
            else:
                # 超出总量限制,该材料完全未送入模型
                coverage.append(MaterialCoverage(
                    material_id=d.material_id,
                    filename=d.filename,
                    role=role,
                    total_chars=total_chars,
                    checked_chars=0,
                    truncated=total_chars > 0,
                ))
        return "\n\n".join(parts) or "(无材料)", coverage


    # ---- 6. 主张-证据图:模型候选边提案 ----

    def propose_graph_candidates(self, session_id: str) -> dict:
        """让模型提出规则可能遗漏的候选子主张/候选边。

        模型只提案(source=llm, status=pending),由用户逐条确认后生效。
        候选边引用的 fact_id 必须在已确认事实中存在,否则丢弃(防幻觉)。
        """
        from app.models.claim_graph import (
            ClaimEvidenceEdge,
            EdgeRelation,
            EvidenceDirection,
            SubClaim,
            TestAspect,
        )
        from app.services.claim_graph import claim_graph_service

        store = data_store.require(session_id)
        graph = store.claim_graph
        if graph is None:
            return {"status": "no_graph", "message": "尚未构建主张-证据图,请先构建规则图", "added": 0}

        if not llm_client.is_available():
            return {"status": "llm_unavailable", "message": "未接入模型,候选边提案需要 LLM 支持", "added": 0}

        usable = store.usable_facts()
        claims_text = "\n".join(f"- [{c.claim_id}] {c.text}" for c in store.session.claims)
        facts_text = "\n".join(
            f"- [{f.fact_id}] [{f.category.value}] {f.effective_value()}" for f in usable
        ) or "(无已确认事实)"
        existing_sc = "\n".join(f"- [{sc.test_aspect.value}] {sc.text}" for sc in graph.sub_claims) or "(无)"
        existing_edges = "\n".join(
            f"- {sc_text} <-{e.relation.value}- fact:{e.fact_id}"
            for e in graph.edges
            for sc_text in [next((s.text for s in graph.sub_claims if s.sub_claim_id == e.sub_claim_id), "?")]
        ) or "(无)"

        raw = llm_client.chat(
            prompts.GRAPH_CANDIDATE_SYSTEM,
            prompts.GRAPH_CANDIDATE_USER.format(
                claims=claims_text,
                facts=facts_text,
                existing_sub_claims=existing_sc,
                existing_edges=existing_edges,
            ),
            retries=1,
        )
        if raw is None:
            return {"status": "llm_call_failed", "message": "模型调用失败,候选边未生成", "added": 0}

        data = llm_client.parse_json_response(raw)
        if not isinstance(data, dict):
            return {"status": "llm_parse_failed", "message": "模型输出解析失败,候选边未生成", "added": 0}

        # 校验:候选边引用的 fact_id 必须存在
        valid_fact_ids = {f.fact_id for f in usable}
        claim_ids = {c.claim_id for c in store.session.claims}
        existing_texts = {sc.text for sc in graph.sub_claims}

        cand_subs: list[SubClaim] = []
        for item in data.get("candidate_sub_claims", []) or []:
            if not isinstance(item, dict):
                continue
            text = (item.get("text") or "").strip()
            cid = item.get("claim_id") or ""
            if not text or text in existing_texts or cid not in claim_ids:
                continue
            try:
                aspect = TestAspect(item.get("test_aspect", "other"))
            except ValueError:
                continue
            cand_subs.append(SubClaim(
                claim_id=cid,
                text=text,
                test_aspect=aspect,
                scope_keywords=item.get("scope_keywords") or [],
            ))

        # 子主张文本 -> SubClaim 对象(含新提出的)
        sc_by_text = {sc.text: sc for sc in graph.sub_claims}
        for sc in cand_subs:
            sc_by_text[sc.text] = sc

        cand_edges: list[ClaimEvidenceEdge] = []
        for item in data.get("candidate_edges", []) or []:
            if not isinstance(item, dict):
                continue
            sc_text = (item.get("sub_claim_text") or "").strip()
            fact_id = item.get("fact_id") or ""
            target_sc = sc_by_text.get(sc_text)
            if target_sc is None or fact_id not in valid_fact_ids:
                continue  # 引用不存在的事实或子主张:丢弃,防幻觉
            try:
                relation = EdgeRelation(item.get("relation", "unknown"))
                direction = EvidenceDirection(item.get("direction", "execution"))
            except ValueError:
                continue
            cand_edges.append(ClaimEvidenceEdge(
                sub_claim_id=target_sc.sub_claim_id,
                fact_id=fact_id,
                relation=relation,
                basis=(item.get("basis") or "模型提案,未给出依据").strip(),
                direction=direction,
            ))

        added = 0
        if cand_subs or cand_edges:
            claim_graph_service.add_candidates(session_id, cand_subs, cand_edges)
            added = len(cand_subs) + len(cand_edges)

        return {
            "status": "ok",
            "message": f"模型提出了 {len(cand_subs)} 条候选子主张、{len(cand_edges)} 条候选边,等待确认" if added else "模型未发现规则遗漏的候选边",
            "added": added,
            "candidate_sub_claims": len(cand_subs),
            "candidate_edges": len(cand_edges),
        }

    # ---- 7. 学习迁移题(P2) ----

    def generate_migration_question(self, session_id: str) -> dict:
        """根据原发现生成不同表面情境、同一方法要点的迁移题。

        Returns:
            {status, message, question}
        """
        from app.models.version_diff import MigrationQuestion

        store = data_store.require(session_id)
        report = store.latest_report()
        if report is None or not report.findings:
            return {"status": "no_findings", "message": "尚无审查发现,无法生成迁移题", "question": None}

        # 取最严重的发现作为迁移题来源
        level_order = {FindingLevel.CONTRADICTION: 0, FindingLevel.RISK: 1, FindingLevel.INSUFFICIENT: 2}
        source_finding = min(report.findings, key=lambda f: level_order.get(f.level, 9))

        claims_text = "\n".join(f"- {c.text}" for c in store.session.claims)
        exp_label = store.session.experiment_type.value

        if llm_client.is_available():
            raw = llm_client.chat(
                prompts.MIGRATION_SYSTEM,
                prompts.MIGRATION_USER.format(
                    experiment_type=exp_label,
                    claims=claims_text,
                    rule_id=source_finding.rule_id,
                    title=source_finding.title,
                    reasoning=source_finding.reasoning,
                    suggestion=source_finding.suggestion,
                ),
                temperature=0.7,
                retries=1,
            )
            if raw:
                data = llm_client.parse_json_response(raw)
                if isinstance(data, dict) and data.get("scenario"):
                    q = MigrationQuestion(
                        session_id=session_id,
                        source_finding_id=source_finding.finding_id,
                        source_rule_id=source_finding.rule_id,
                        method_point=data.get("method_point", ""),
                        scenario=data["scenario"],
                        question=data.get("question", ""),
                        hint=data.get("hint", ""),
                        reference_answer=data.get("reference_answer", ""),
                        created_at=datetime.now().isoformat(),
                    )
                    store.migration_questions.append(q)
                    data_store.persist(session_id)
                    return {"status": "ok", "message": "迁移题已生成", "question": q, "source": "llm"}

        # 启发式降级:基于规则类型的预设迁移情境
        q = self._preset_migration(store, source_finding)
        store.migration_questions.append(q)
        data_store.persist(session_id)
        return {"status": "ok", "message": "迁移题已生成(预设情境)", "question": q, "source": "preset"}

    @staticmethod
    def _preset_migration(store, source_finding) -> "MigrationQuestion":
        """预设迁移情境(无模型时降级):按规则类型选不同领域的同构问题。"""
        from app.models.version_diff import MigrationQuestion

        rule = source_finding.rule_id
        if "split" in rule or "generalization" in rule:
            return MigrationQuestion(
                session_id=store.session.session_id,
                source_finding_id=source_finding.finding_id,
                source_rule_id=rule,
                method_point="泛化到新实体需要按组划分,防止同一实体数据泄漏",
                scenario=(
                    "小红做文本情感分类研究,主张'模型能准确分类新作者的文章'。"
                    "她收集了 200 位作者的文章,用 train_test_split 随机划分后训练,"
                    "测试准确率 94%,得出结论。"
                ),
                question="小红的实验能支持她的结论吗?问题出在哪里?",
                hint="注意她的主张是'新作者',再看看她的划分方式。",
                reference_answer=(
                    "漏洞:主张是分类'新作者'的文章,但随机划分会让同一作者的文章"
                    "同时出现在训练集和测试集(数据泄漏),模型可能记住了已知作者的写作风格。"
                    "修改:按作者 ID 分组划分,确保测试集只含训练时未见过的作者。"
                ),
                created_at=datetime.now().isoformat(),
            )
        if "repetition" in rule or "stability" in rule:
            return MigrationQuestion(
                session_id=store.session.session_id,
                source_finding_id=source_finding.finding_id,
                source_rule_id=rule,
                method_point="稳定性/可重复性主张需要多次运行的波动数据支持",
                scenario=(
                    "小刚研究推荐算法,主张'算法 X 比算法 Y 在不同数据分布下更鲁棒'。"
                    "他各运行了一次实验,算法 X 的 NDCG 为 0.81,算法 Y 为 0.79,得出结论。"
                ),
                question="小刚的实验能支持'更鲁棒'的结论吗?",
                hint="'鲁棒'意味着什么?单次运行能体现吗?",
                reference_answer=(
                    "漏洞:'更鲁棒'需要多次运行、多种数据分布下的表现对比,"
                    "单次运行只能说明这一次略好,无法体现鲁棒性。"
                    "修改:在多种数据分布下各运行多次,比较均值和方差的差异。"
                ),
                created_at=datetime.now().isoformat(),
            )
        return MigrationQuestion(
            session_id=store.session.session_id,
            source_finding_id=source_finding.finding_id,
            source_rule_id=rule,
            method_point="比较主张需要基线方法在同等条件下的对比结果",
            scenario=(
                "小美提出了新的图像分割模型,主张'新模型优于现有方法'。"
                "她只运行了新模型,mIoU 达到 78%,没有运行任何基线,得出结论。"
            ),
            question="小美的实验能支持'优于现有方法'的结论吗?",
            hint="比较需要什么?",
            reference_answer=(
                "漏洞:没有基线方法在相同数据与指标下的结果,'优于'无从谈起。"
                "修改:选择代表性基线,在相同数据划分与指标下运行对比。"
            ),
            created_at=datetime.now().isoformat(),
        )

    # ---- 8. 迁移题评分(看推理过程) ----

    def score_migration_answer(
        self, session_id: str, question_id: str, answer_text: str
    ) -> dict:
        """评分迁移题回答:看推理过程(四维评分)。

        Returns:
            {status, message, answer}
        """
        from app.models.version_diff import MigrationAnswer

        store = data_store.require(session_id)
        question = next(
            (q for q in store.migration_questions if q.question_id == question_id),
            None,
        )
        if question is None:
            return {"status": "not_found", "message": "迁移题不存在", "answer": None}

        answer = MigrationAnswer(
            question_id=question_id,
            session_id=session_id,
            answer_text=answer_text,
            answered_at=datetime.now().isoformat(),
        )

        if llm_client.is_available():
            raw = llm_client.chat(
                prompts.MIGRATION_SCORE_SYSTEM,
                prompts.MIGRATION_SCORE_USER.format(
                    scenario=question.scenario,
                    question=question.question,
                    reference_answer=question.reference_answer,
                    answer_text=answer_text,
                ),
                retries=1,
            )
            if raw:
                data = llm_client.parse_json_response(raw)
                if isinstance(data, dict):
                    import math
                    dims = ("identifies_core_issue", "explains_why", "proposes_fix", "reasoning_quality")
                    values = [data.get(dim) for dim in dims]
                    valid = all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                and math.isfinite(v) and 0 <= v <= 1 for v in values)
                    feedback = data.get("feedback")
                    if valid and isinstance(feedback, str) and feedback.strip():
                        for dim, value in zip(dims, values):
                            setattr(answer, dim, float(value))
                        answer.feedback = feedback.strip()
                        answer.source = "llm"
                        answer.score_status = "model_feedback"
                        answer.total_score = sum(values) / len(values)
                        store.migration_answers.append(answer)
                        data_store.persist(session_id)
                        return {"status": "ok", "message": "已生成模型反馈；单次作答不作为掌握程度证明", "answer": answer}

        answer = self._heuristic_migration_score(question, answer)
        store.migration_answers.append(answer)
        data_store.persist(session_id)
        return {"status": "feedback_only", "message": "暂未获得有效模型评分，已保存作答并提供自查建议", "answer": answer}

    @staticmethod
    def _heuristic_migration_score(question, answer) -> "MigrationAnswer":
        """无法可靠评分时只给检查清单，不把关键词和篇幅换算成掌握分数。"""
        answer.source = "heuristic"
        answer.score_status = "feedback_only"
        for dim in ("identifies_core_issue", "explains_why", "proposes_fix", "reasoning_quality", "total_score"):
            setattr(answer, dim, None)
        answer.feedback = (
            "作答已保存，本次未给分。请对照参考思路逐项检查："
            "是否指出了情境中的具体信息；是否解释了它如何影响结论；"
            "提出的修改能否解决该问题；还需要什么证据验证修改。"
            "可请教师复核，或在模型服务恢复后重新提交。"
        )
        return answer


agent_service = AgentService()
