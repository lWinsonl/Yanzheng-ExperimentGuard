"""事实路由:查看提取事实、用户确认/纠正/拒绝。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import data_store, evidence_chain

router = APIRouter(prefix="/api/sessions/{session_id}/facts", tags=["facts"])


@router.get("")
def list_facts(session_id: str, status: str | None = None):
    """列出事实。可选按状态过滤:pending_user_confirm/confirmed/corrected/rejected。"""
    store = data_store.get(session_id)
    if store is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    facts = store.facts_for_session()
    if status:
        facts = [f for f in facts if f.status.value == status]
    return facts


class ConfirmFactRequest(BaseModel):
    action: str  # confirm / correct / reject
    corrected_value: str | None = None


@router.post("/{fact_id}/confirm")
def confirm_fact(session_id: str, fact_id: str, req: ConfirmFactRequest):
    """用户对事实的裁决:确认 / 纠正 / 拒绝。"""
    try:
        fact = evidence_chain.confirm_fact(
            session_id, fact_id, req.action, req.corrected_value
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return fact


@router.post("/confirm-all")
def confirm_all_pending(session_id: str):
    """一键确认所有待确认事实(学生已逐条过目后的批量操作)。"""
    store = data_store.get(session_id)
    if store is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    updated = []
    for fact in store.facts_for_session():
        if fact.status.value == "pending_user_confirm":
            updated.append(evidence_chain.confirm_fact(session_id, fact.fact_id, "confirm"))
    return {"confirmed_count": len(updated), "facts": updated}