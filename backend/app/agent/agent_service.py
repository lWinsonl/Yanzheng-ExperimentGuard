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

    # ---- 4. 模型复核(复杂上下文,引用校验) ----

    def deep_review(self, session_id: str) -> list[DeepFinding]:
        """模型复核:处理规则无法覆盖的复杂上下文。引用必须逐字校验。"""
        store = data_store.require(session_id)
        session = store.session

        if not llm_client.is_available():
            return []

        report = store.latest_report()
        existing = ""
        if report:
            existing = "\n".join(f"- [{f.level.value}] {f.title}" for f in report.findings)

        # 拼接材料内容(限制总长度防超 token)
        materials_text = self._materials_text(store, max_chars=8000)
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
        )
        data = llm_client.parse_json_response(raw)
        if not isinstance(data, dict) or not isinstance(data.get("deep_findings"), list):
            return []

        results: list[DeepFinding] = []
        for item in data["deep_findings"]:
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
            finding.quote_verified = self._verify_quote(store, finding.verified_quote)
            if finding.verified_quote and not finding.quote_verified:
                # 引用未通过逐字校验(模型轻微改写):不展示该引用,但保留发现与建议
                logger.warning("模型复核引用校验失败(清除引用,保留发现):%s", finding.title)
                finding.verified_quote = ""
                finding.material_filename = ""
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
    def _materials_text(store: SessionStore, max_chars: int = 8000) -> str:
        parts = []
        total = 0
        for d in store.docs.values():
            content = d.content[:2000]
            total += len(content)
            if total > max_chars:
                break
            role = "计划" if d.role == MaterialRole.PLAN else "执行"
            parts.append(f"=== [{role}] {d.filename} ===\n{content}")
        return "\n\n".join(parts) or "(无材料)"


agent_service = AgentService()