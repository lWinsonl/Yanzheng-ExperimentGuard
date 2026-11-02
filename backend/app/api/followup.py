"""主动追问路由:生成排序追问、回答追踪、统计。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.followup import followup_service

router = APIRouter(prefix="/api/sessions/{session_id}/followups", tags=["followups"])


class AnswerRequest(BaseModel):
    answer_text: str = Field(min_length=1, max_length=20000)


class SkipRequest(BaseModel):
    pass


@router.post("/generate")
def generate_followups(session_id: str):
    """生成基于预期信息价值的主动追问(可解释 EIV 排序)。"""
    from app.agent.agent_service import agent_service

    try:
        return agent_service.generate_ranked_followups(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("")
def list_followups(session_id: str):
    """获取当前追问列表(按 EIV 排序)。"""
    try:
        questions = followup_service.get_questions(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"questions": questions}


@router.post("/{question_id}/answer")
def answer_question(session_id: str, question_id: str, req: AnswerRequest):
    """记录用户回答,重算审查并追踪该回答是否实际改变了发现。"""
    try:
        q = followup_service.record_answer(session_id, question_id, req.answer_text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return q


@router.post("/{question_id}/review")
def review_answer(session_id: str, question_id: str):
    """新事实全部裁决后,重新审查并对比原发现。"""
    try:
        return followup_service.review_answer(session_id, question_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{question_id}/skip")
def skip_question(session_id: str, question_id: str):
    """用户跳过追问。"""
    try:
        q = followup_service.skip_question(session_id, question_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return q


@router.get("/stats")
def get_stats(session_id: str):
    """单会话追问统计(完成率/变化率/平均追问数)。"""
    return followup_service.get_stats(session_id)


@router.get("/global-stats")
def get_global_stats():
    """跨会话追问统计(离线比较排序前后效果)。"""
    raise HTTPException(status_code=404, detail="公开演示不提供跨浏览器会话统计")
