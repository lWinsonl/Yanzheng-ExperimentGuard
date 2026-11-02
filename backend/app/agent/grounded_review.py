"""Validate model proposals against this request's evidence catalog, not free quotes."""
from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.review_context import build_context


class ProposedFinding(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", str_strip_whitespace=True)
    issue_kind: Literal["entity_isolation", "recall_defined", "comparison", "stability", "target_semantics", "other"]
    level: Literal["contradiction", "risk", "insufficient"]
    title: str = Field(min_length=1, max_length=140)
    reasoning: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=1, max_length=6)
    suggestion_type: Literal["fix", "narrow", "clarify"] = "clarify"
    suggestion_action: str = Field(default="", max_length=800)
    suggestion_reason: str = Field(default="", max_length=500)
    suggestion_verify: str = Field(default="", max_length=500)


def parse_proposals(items, context):
    from app.agent.agent_service import DeepFinding

    evidence = {e.evidence_id: e for e in context.evidence}
    checks = {c.check_id: c for c in context.checks[:24]}
    accepted, unverified = [], []
    for item in items[:8]:
        title = item.get("title", "未采纳的模型输出") if isinstance(item, dict) else "未采纳的模型输出"
        title = title[:140] if isinstance(title, str) else "未采纳的模型输出"
        reason = ""
        # Computed evidence is already typed by the server. The model cannot
        # invent a check ID, reclassify that result, or override its status.
        item = dict(item) if isinstance(item, dict) else item
        raw_ids = item.get("evidence_ids", []) if isinstance(item, dict) else []
        bound_checks = []
        if isinstance(raw_ids, list) and all(isinstance(eid, str) for eid in raw_ids):
            bound_checks = [checks[evidence[eid].check_id] for eid in raw_ids
                            if eid in evidence and evidence[eid].source_kind == "program_result"
                            and evidence[eid].check_id in checks]
        if bound_checks and len({c.kind for c in bound_checks}) == 1:
            item["issue_kind"] = bound_checks[0].kind
        try:
            proposal = ProposedFinding.model_validate(item)
        except ValidationError:
            reason = "字段不符合证据编号协议，未采纳其推断和修改操作。"
        else:
            refs = [evidence[eid] for eid in proposal.evidence_ids if eid in evidence]
            selected = list({c.check_id: c for c in bound_checks}.values())
            if len(refs) != len(proposal.evidence_ids):
                reason = "引用了本轮不存在的证据编号，未采纳修改操作。"
            elif len({c.kind for c in selected}) > 1:
                reason = "一条输出混合了不同检查，请分开核对，未采纳修改操作。"
            elif any(not set(c.material_ids) & {e.material_id for e in refs} for c in selected):
                reason = "检查编号与引用材料不对应，未采纳修改操作。"
            elif proposal.issue_kind in ("entity_isolation", "recall_defined", "comparison", "stability"):
                relevant = [c for c in context.checks if c.kind == proposal.issue_kind]
                if any(c.kind != proposal.issue_kind for c in selected):
                    reason = "该检查与模型所声称的问题类型不对应。"
                elif proposal.level != "insufficient" and (not selected or any(c.status != "failed" for c in selected)):
                    reason = "程序没有确认该项失败，不能将未知或已通过的检查报告为确定问题。"
                elif relevant and not selected:
                    reason = "已有该项程序结果，但模型没有绑定它，未采纳重复猜测。"
                elif selected and all(c.status == "passed" for c in selected):
                    reason = "引用的程序检查已通过，不能将同一项再次报告为未核实或需要修复。"
            if not reason:
                action, why, verify = proposal.suggestion_action, proposal.suggestion_reason, proposal.suggestion_verify
                if proposal.level == "insufficient":
                    # Missing proof permits a request for evidence, not an order to retrain.
                    action = "请补充能核对该问题的原始材料，再决定是否修改实验。"
                    why = "目前证据不足，不能从缺少信息推断实验有错。"
                    verify = "补充后确认事实，并重新运行对应程序检查。"
                suggestion_type = "clarify" if proposal.level == "insufficient" else proposal.suggestion_type
                if selected and all(c.status == "failed" for c in selected):
                    # For calculated predicates, a verified remediation contract
                    # takes precedence over unchecked model instructions.
                    if proposal.issue_kind == "entity_isolation":
                        suggestion_type = "fix"
                        action = "按原始实体编号分组，使同源样本留在同一侧；重新评估并导出新的完整训练/测试编号记录。仅减少复制次数或更改随机种子不构成隔离证明。"
                        why = "当前完整编号记录已出现交集，原问题是同源实体跨集合，而非复制次数本身。"
                        verify = "确认新记录后重算实体交集，要求交集为0；同时核对前后实验范围与记录来源。"
                    elif proposal.issue_kind == "recall_defined":
                        suggestion_type = "narrow"
                        action = "将这份表的召回率标为不可估计。需要估计时，按原任务规则取得含真实正类的新评估记录；不能为得到指标改标签或挑选样本。"
                        why = "TP+FN为0时没有可用于估计召回率的实际正类。"
                        verify = "核对正类定义和抽样范围，再重算TP+FN；改变评估窗口或人群时明确说明新的适用范围。"
                    elif proposal.issue_kind in ("comparison", "stability"):
                        suggestion_type = "narrow"
                        action = "核对完整原始记录、方法与指标定义；若记录无误，应修正当前限定主张，或提供相同条件下的新实际结果。"
                        why = "所提供数值未通过这项限定比较，不能靠更换指标、删除运行或口头解释改变观测。"
                        verify = "确认新记录并重跑同一比较，保留前后条件、所有运行和结论范围。"
                raw_refs = [e for e in refs if e.source_kind == "uploaded_excerpt"]
                accepted.append(DeepFinding(level=proposal.level, title=proposal.title, reasoning=proposal.reasoning,
                    verified_quote=raw_refs[0].text if raw_refs else "",
                    material_filename=raw_refs[0].filename if raw_refs else refs[0].filename,
                    quote_verified=bool(raw_refs), suggestion_action=action, suggestion_reason=why,
                    suggestion_verify=verify, suggestion_type=suggestion_type,
                    suggestion="\n".join(x for x in (action, why, verify) if x),
                    evidence_ids=proposal.evidence_ids, evidence=[asdict(e) for e in refs],
                    check_ids=[c.check_id for c in selected], evidence_verified=True,
                    validation_check_ids=[c.check_id for c in selected if c.status == "failed"],
                    validation_status=("awaiting_new_records" if any(c.status == "failed" for c in selected)
                        else "manual_verification_required") if action and suggestion_type == "fix" else "not_executed"))
        if reason:
            unverified.append({"title": title, "reason": reason})
    if len(items) > 8:
        unverified.append({"title": "输出条数超限", "reason": "只处理前8项，超出部分没有用于判断。"})
    return accepted, unverified


def run_grounded_review(session_id, store, client):
    from app.agent import prompts
    from app.agent.agent_service import DeepReviewResult, MaterialCoverage

    import hashlib
    import json
    def snapshot_signature():
        return hashlib.sha256(json.dumps({
            "claims": [c.model_dump(mode="json") for c in store.session.claims],
            "docs": [d.model_dump(mode="json") for d in store.docs.values()],
            "facts": [f.model_dump(mode="json") for f in store.facts.values()],
        }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    signature = snapshot_signature()
    context = build_context(store)
    common = dict(coverage=[MaterialCoverage(**c) for c in context.coverage],
                  checks=[c.model_dump(mode="json") for c in context.checks],
                  evidence_catalog=[asdict(e) for e in context.evidence],
                  validation_note="程序结果仅针对已确认的提供记录；模型证据绑定通过不代表推理正确，建议执行后仍需新记录验证。")
    if not client.is_available():
        return DeepReviewResult(status="llm_unavailable", message="未配置模型服务；可先查看程序核对结果。", **common)
    report = store.latest_report()
    findings = [{"rule_id": f.rule_id, "level": f.level.value, "title": f.title,
                 "reasoning": f.reasoning[:500]} for f in report.findings] if report else []
    raw = client.chat(prompts.GROUNDED_REVIEW_SYSTEM,
        json.dumps({"claims": [{"claim_id": c.claim_id, "text": c.text} for c in store.session.claims],
                    "review_context": json.loads(context.prompt_text()), "rule_findings": findings}, ensure_ascii=False),
        max_tokens=2500, timeout=45, retries=0)
    if snapshot_signature() != signature:
        current = build_context(store)
        common["checks"] = [c.model_dump(mode="json") for c in current.checks]
        common["evidence_catalog"] = []
        return DeepReviewResult(status="needs_evidence", message="复核期间材料、主张或事实状态已改变；旧模型输出未采用，程序结果已更新，请重新复核。",
            unverified=[{"title": "材料已改变", "reason": "旧输出不能用于当前版本，未采用任何修改操作。"}], llm_available=True, **common)
    if raw is None:
        return DeepReviewResult(status="llm_call_failed", message="模型调用未完成，已保留程序核对结果。", llm_available=True, **common)
    data = client.parse_json_response(raw)
    if not isinstance(data, dict) or not isinstance(data.get("deep_findings"), list):
        return DeepReviewResult(status="llm_parse_failed", message="模型输出格式无效；未采用其中的修改操作，程序结果仍可查看。", llm_available=True, **common)
    accepted, unverified = parse_proposals(data["deep_findings"], context)
    status = "ok" if accepted else "needs_evidence" if unverified else "ok_no_findings"
    return DeepReviewResult(status=status, message="有模型输出未通过校验，已放入待核实区并隐藏修改操作。" if unverified else "",
                            findings=accepted, unverified=unverified, llm_available=True, **common)
