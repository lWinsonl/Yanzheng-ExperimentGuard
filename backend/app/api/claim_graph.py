"""主张—证据图路由:构建、查询、用户校准、模型候选边。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.claim_graph import claim_graph_service

router = APIRouter(prefix="/api/sessions/{session_id}/claim-graph", tags=["claim-graph"])


class EdgeConfirmRequest(BaseModel):
    action: str  # confirm / correct / reject
    corrected_relation: str | None = None  # supports / contradicts / unknown


class SubClaimConfirmRequest(BaseModel):
    action: str  # confirm / reject


@router.post("/build")
def build_graph(session_id: str):
    """基于已确认事实,确定性构建主张—证据图。"""
    try:
        graph = claim_graph_service.build_graph(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return graph


@router.get("")
def get_graph(session_id: str):
    """获取当前主张—证据图。"""
    graph = claim_graph_service.get_graph(session_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="尚未构建主张-证据图")
    return graph


@router.post("/edges/{edge_id}/confirm")
def confirm_edge(session_id: str, edge_id: str, req: EdgeConfirmRequest):
    """用户对边的裁决:确认 / 纠正关系 / 拒绝。"""
    try:
        edge = claim_graph_service.confirm_edge(
            session_id, edge_id, req.action, req.corrected_relation
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return edge


@router.post("/sub-claims/{sub_claim_id}/confirm")
def confirm_sub_claim(session_id: str, sub_claim_id: str, req: SubClaimConfirmRequest):
    """用户对模型候选子主张的裁决:确认 / 拒绝(拒绝时级联拒绝其下所有边)。"""
    try:
        sc = claim_graph_service.confirm_sub_claim(session_id, sub_claim_id, req.action)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return sc


@router.post("/candidates")
def propose_candidates(session_id: str):
    """让模型提出规则可能遗漏的候选子主张/候选边(待用户确认)。"""
    from app.agent.agent_service import agent_service

    try:
        return agent_service.propose_graph_candidates(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc