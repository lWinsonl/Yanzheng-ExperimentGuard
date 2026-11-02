"""基于预期信息价值的追问服务。

核心差异化(P1):
从固定缺口清单升级为"回答哪个问题最可能改变审查结论",同时考虑用户补材料成本。

评分公式(可解释):
    EIV = severity_score × uncertainty × change_probability / cost_factor

排序流程:
1. 从审查报告的 insufficient 发现出发,生成追问候选。
2. 为每条追问估计四个因子,计算 EIV 并排序。
3. 展示"为何先问这个"(score_explanation)。
4. 收到回答后:重算审查,记录该回答是否实际改变了发现。
5. 提供统计接口,用于离线比较排序前后用户完成率、结论变化率与平均追问数。
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.models.followup import (
    AnswerCost,
    EvidenceType,
    FollowupQuestion,
    FollowupStats,
    FollowupStatus,
)
from app.models.review import FindingLevel
from app.services.store import data_store

logger = logging.getLogger("followup")

# 严重度映射
_SEVERITY_MAP = {
    FindingLevel.CONTRADICTION: 3.0,
    FindingLevel.RISK: 2.0,
    FindingLevel.INSUFFICIENT: 1.0,
}

# 成本因子映射
_COST_MAP = {
    AnswerCost.LOW: 1.0,
    AnswerCost.MEDIUM: 2.0,
    AnswerCost.HIGH: 3.0,
}


class FollowupService:
    """追问服务:评分、排序、回答追踪、统计。"""

    # ---- 评分与排序 ----

    def score_and_rank(
        self,
        questions: list[FollowupQuestion],
        target_finding_levels: dict[str, str] | None = None,
    ) -> list[FollowupQuestion]:
        """为追问列表计算 EIV 评分并排序(降序)。

        Args:
            questions: 待评分的追问列表。
            target_finding_levels: finding_id -> level 字符串,用于推断严重度。
                                    若追问自身未设置 severity_score 则据此推断。

        Returns:
            排序后的追问列表(原地修改 rank/eiv_score/score_explanation)。
        """
        levels = target_finding_levels or {}

        for q in questions:
            # 严重度:优先用已设置的值,否则从目标发现级别推断
            if q.severity_score <= 0:
                level_str = levels.get(q.target_finding_id, "insufficient")
                try:
                    q.severity_score = _SEVERITY_MAP[FindingLevel(level_str)]
                except ValueError:
                    q.severity_score = 1.0

            # 成本因子
            if q.cost_factor <= 0:
                q.cost_factor = 2.0

            # EIV = severity × uncertainty × change_probability / cost
            q.eiv_score = (
                q.severity_score * q.uncertainty * q.change_probability / q.cost_factor
            )

            # 可解释评分说明
            q.score_explanation = self._explain_score(q)

        # 降序排序,分配 rank
        questions.sort(key=lambda q: q.eiv_score, reverse=True)
        for i, q in enumerate(questions):
            q.rank = i + 1

        return questions

    @staticmethod
    def _explain_score(q: FollowupQuestion) -> str:
        """生成可解释的评分说明:"为何先问这个"。"""
        cost_label = {1.0: "低", 2.0: "中", 3.0: "高"}.get(q.cost_factor, "中")
        parts = [
            f"严重度 {q.severity_score:.0f}/3",
            f"不确定性 {q.uncertainty:.0%}",
            f"可改变概率 {q.change_probability:.0%}",
            f"回答成本 {cost_label}({q.cost_factor:.0f})",
        ]
        return (
            f"预期信息价值 EIV={q.eiv_score:.2f} = "
            f"严重度×不确定性×可改变概率÷成本 ({' × '.join(parts[:3])} ÷ {q.cost_factor:.0f})"
        )

    # ---- 生成追问(从发现+子主张出发) ----

    def generate_from_findings(
        self,
        session_id: str,
        raw_questions: list[dict],
    ) -> list[FollowupQuestion]:
        """把 LLM/启发式生成的原始追问列表转为带评分的 FollowupQuestion。

        raw_questions 每项包含:
            question, what_to_provide, why_needed,
            target_finding_id(可选), target_finding_title(可选),
            sub_claim_id(可选), evidence_type(可选), evidence_format(可选),
            uncertainty(可选,0-1), change_probability(可选,0-1),
            answer_cost(可选,low/medium/high)
        """
        store = data_store.require(session_id)
        report = store.latest_report()
        finding_levels = {
            f.finding_id: f.level.value for f in (report.findings if report else [])
        }

        questions: list[FollowupQuestion] = []
        for item in raw_questions:
            if not isinstance(item, dict) or not item.get("question"):
                continue

            cost_str = item.get("answer_cost", "medium")
            try:
                cost = AnswerCost(cost_str)
            except ValueError:
                cost = AnswerCost.MEDIUM

            et_str = item.get("evidence_type", "explanation")
            try:
                etype = EvidenceType(et_str)
            except ValueError:
                etype = EvidenceType.EXPLANATION

            # 严重度从目标发现推断
            fid = item.get("target_finding_id", "")
            severity = _SEVERITY_MAP.get(
                FindingLevel(finding_levels.get(fid, "insufficient")), 1.0
            )

            q = FollowupQuestion(
                session_id=session_id,
                target_finding_id=fid,
                target_finding_title=item.get("target_finding_title", ""),
                sub_claim_id=item.get("sub_claim_id", ""),
                question=item["question"],
                what_to_provide=item.get("what_to_provide", ""),
                why_needed=item.get("why_needed", ""),
                evidence_type=etype,
                evidence_format=item.get("evidence_format", ""),
                severity_score=severity,
                uncertainty=float(item.get("uncertainty", 0.5)),
                change_probability=float(item.get("change_probability", 0.5)),
                cost_factor=_COST_MAP[cost],
                created_at=datetime.now().isoformat(),
            )
            questions.append(q)

        return self.score_and_rank(questions, finding_levels)

    # ---- 存取 ----

    def save_questions(self, session_id: str, questions: list[FollowupQuestion]) -> None:
        """保存追问列表到会话(替换旧列表)。"""
        store = data_store.require(session_id)
        history = [q for q in store.followup_questions if q.status != FollowupStatus.PENDING]
        asked = {(q.question, q.target_finding_title) for q in history}
        store.followup_questions = history + [q for q in questions if (q.question, q.target_finding_title) not in asked]
        data_store.persist(session_id)

    def get_questions(self, session_id: str) -> list[FollowupQuestion]:
        store = data_store.get(session_id)
        return store.followup_questions if store else []

    # ---- 回答追踪 ----

    def record_answer(self, session_id: str, question_id: str, answer_text: str) -> FollowupQuestion:
        """回答作为独立材料保存,所有新事实先等待用户裁决。"""
        from app.models.evidence import ExtractedFact, FactCategory, SourceSpan
        from app.services.evidence_chain import evidence_chain

        store = data_store.require(session_id)
        q = next((q for q in store.followup_questions if q.question_id == question_id), None)
        if q is None:
            raise KeyError(f"追问不存在:{question_id}")
        text = answer_text.strip()
        if not text:
            raise ValueError("请输入回答内容")
        if q.answer_material_id:
            if q.answer_text == text:
                return q  # 重试不创建重复材料
            raise ValueError("此回答已保存；请通过补充材料更正，并重新确认事实")

        old_report = store.latest_report()
        doc, facts, _ = evidence_chain.extract_from_text(
            session_id, text, f"followup-{q.question_id}.txt", "execution"
        )
        doc.origin = "followup_answer"
        if not facts:
            fact = ExtractedFact(
                session_id=session_id, category=FactCategory.OTHER, value=text,
                source=SourceSpan(material_id=doc.material_id, start_char=0,
                                  end_char=len(text), snippet=text),
                note="用户补充说明；尚未识别为可用于具体规则的执行证据",
            )
            store.add_fact(fact)
            facts = [fact]
        for fact in facts:
            fact.note = "追问回答（用户说明，非独立运行证明）。" + fact.note
        q.answer_text = text
        q.answered_at = datetime.now().isoformat()
        q.status = FollowupStatus.ANSWERED
        q.answer_material_id = doc.material_id
        q.answer_fact_ids = [f.fact_id for f in facts]
        q.baseline_report_id = old_report.report_id if old_report else ""
        q.review_state = "awaiting_confirmation"
        q.answer_changed_finding = False
        q.finding_change_detail = "回答已保存。请核对新提取的事实，确认或拒绝后再重新审查。"
        data_store.persist(session_id)
        return q

    def review_answer(self, session_id: str, question_id: str) -> FollowupQuestion:
        from app.models.evidence import FactStatus
        from app.services.review import review_service

        store = data_store.require(session_id)
        q = next((q for q in store.followup_questions if q.question_id == question_id), None)
        if q is None:
            raise KeyError(f"追问不存在:{question_id}")
        if not q.answer_material_id:
            raise ValueError("请先提交回答")
        facts = [store.facts.get(fid) for fid in q.answer_fact_ids]
        if any(f is None for f in facts):
            raise ValueError("回答材料已变更，请重新补充材料")
        if any(f.status == FactStatus.PENDING for f in facts):
            raise ValueError("请先逐条确认、纠正或拒绝回答中提取的事实")
        old_report = store.reports.get(q.baseline_report_id)
        old = next((f for f in old_report.findings if f.finding_id == q.target_finding_id), None) if old_report else None
        new_report = review_service.run_review(session_id)
        q.review_state = "reviewed"
        q.answer_changed_finding = False
        if old is None:
            q.finding_change_detail = "审查已更新；此追问未绑定可对比的原发现，无法归因其变化。"
        else:
            candidates = [f for f in new_report.findings if f.rule_id == old.rule_id
                          and set(f.claim_ids) == set(old.claim_ids)]
            if not candidates:
                q.answer_changed_finding = True
                q.finding_change_detail = "重新审查后原发现不再触发；这不代表整个实验已通过审查。"
            elif len(candidates) != 1:
                q.finding_change_detail = "存在多个同类发现，暂不能可靠配对；请查看最新报告。"
            elif candidates[0].level != old.level or candidates[0].title != old.title:
                q.answer_changed_finding = True
                q.finding_change_detail = f"重新审查后发现有变化：{_level_label(old.level)} → {_level_label(candidates[0].level)}。{candidates[0].title}"
            else:
                q.finding_change_detail = "原发现仍存在。补充说明已纳入审查，仍需所列的代码或运行记录。"
        store.claim_graph = None  # 下次打开证据图时按新事实重建
        data_store.persist(session_id)
        return q

    def skip_question(self, session_id: str, question_id: str) -> FollowupQuestion:
        """用户跳过追问。"""
        store = data_store.require(session_id)
        q = next(
            (fq for fq in store.followup_questions if fq.question_id == question_id),
            None,
        )
        if q is None:
            raise KeyError(f"追问不存在:{question_id}")
        q.status = FollowupStatus.SKIPPED
        data_store.persist(session_id)
        return q

    # ---- 统计(离线比较用) ----

    def get_stats(self, session_id: str) -> FollowupStats:
        """单会话追问统计。"""
        questions = self.get_questions(session_id)
        answered = sum(1 for q in questions if q.status == FollowupStatus.ANSWERED)
        skipped = sum(1 for q in questions if q.status == FollowupStatus.SKIPPED)
        pending = sum(1 for q in questions if q.status == FollowupStatus.PENDING)
        changed = sum(1 for q in questions if q.answer_changed_finding)
        total = len(questions)

        return FollowupStats(
            total_questions=total,
            answered=answered,
            skipped=skipped,
            pending=pending,
            changed_findings=changed,
            completion_rate=answered / total if total else 0.0,
            change_rate=changed / answered if answered else 0.0,
            avg_questions=float(total),
            avg_eiv_top=max((q.eiv_score for q in questions), default=0.0),
        )

    def get_global_stats(self) -> FollowupStats:
        """跨会话追问统计(用于离线比较排序前后效果)。"""
        all_questions: list[FollowupQuestion] = []
        session_count = 0
        for sid in list(data_store._sessions.keys()):
            qs = self.get_questions(sid)
            if qs:
                all_questions.extend(qs)
                session_count += 1

        answered = sum(1 for q in all_questions if q.status == FollowupStatus.ANSWERED)
        skipped = sum(1 for q in all_questions if q.status == FollowupStatus.SKIPPED)
        pending = sum(1 for q in all_questions if q.status == FollowupStatus.PENDING)
        changed = sum(1 for q in all_questions if q.answer_changed_finding)
        total = len(all_questions)

        return FollowupStats(
            total_questions=total,
            answered=answered,
            skipped=skipped,
            pending=pending,
            changed_findings=changed,
            completion_rate=answered / total if total else 0.0,
            change_rate=changed / answered if answered else 0.0,
            avg_questions=total / session_count if session_count else 0.0,
            avg_eiv_top=max((q.eiv_score for q in all_questions), default=0.0),
        )


def _level_label(level) -> str:
    return {
        FindingLevel.CONTRADICTION: "明确矛盾",
        FindingLevel.RISK: "潜在风险",
        FindingLevel.INSUFFICIENT: "信息不足",
    }.get(level, str(level))


followup_service = FollowupService()
