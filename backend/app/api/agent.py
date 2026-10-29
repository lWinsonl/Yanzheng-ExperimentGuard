"""智能体路由:方向审查、缺口分析、自主追问、模型复核、教学案例。"""

from __future__ import annotations

from dataclasses import asdict
from fastapi import APIRouter, HTTPException

from app.agent.agent_service import agent_service
from app.agent.llm_client import llm_client

router = APIRouter(prefix="/api/sessions/{session_id}/agent", tags=["agent"])


def _dataclass_to_dict(obj) -> dict:
    """dataclass 转字典(嵌套 dataclass 递归)。"""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _dataclass_to_dict(v) for k, v in asdict(obj).items()}
    return obj


@router.get("/status")
def agent_status(session_id: str):
    """智能体状态:是否接入模型。"""
    return {
        "llm_available": llm_client.is_available(),
        "mode": "llm" if llm_client.is_available() else "heuristic",
        "note": (
            "已接入大模型,智能体具备语义理解能力"
            if llm_client.is_available()
            else "未接入大模型,智能体运行在启发式降级模式。配置 LLM_API_KEY/LLM_BASE_URL/LLM_MODEL 可获得更深入分析。"
        ),
    }


@router.post("/direction")
def analyze_direction(session_id: str):
    """科研方向审查:理解主张,判断实验设计关键要求。"""
    try:
        result = agent_service.analyze_direction(session_id)
        return _dataclass_to_dict(result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/gaps")
def analyze_gaps(session_id: str):
    """材料缺口分析:判断当前材料是否足以审查,还缺什么。"""
    try:
        result = agent_service.analyze_gaps(session_id)
        return _dataclass_to_dict(result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/followups")
def generate_followups(session_id: str):
    """自主追问:针对'信息不足'的发现生成针对性追问。"""
    try:
        result = agent_service.generate_followups(session_id)
        return {"followups": [_dataclass_to_dict(f) for f in result]}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/deep-review")
def deep_review(session_id: str):
    """模型复核:处理规则无法覆盖的复杂上下文(引用已校验)。"""
    try:
        result = agent_service.deep_review(session_id)
        return {"deep_findings": [_dataclass_to_dict(f) for f in result]}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/teaching-case")
def generate_teaching_case(session_id: str):
    """教学案例:复查后训练实验设计能力。"""
    try:
        result = agent_service.generate_teaching_case(session_id)
        return _dataclass_to_dict(result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc