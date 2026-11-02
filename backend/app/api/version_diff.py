"""版本差异复审与学习迁移评估路由(P2)。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.version_diff import version_diff_service

router = APIRouter(prefix="/api/sessions/{session_id}", tags=["version-diff"])


class VersionDiffRequest(BaseModel):
    revision_note: str = ""


class ManualLabelRequest(BaseModel):
    comparison_id: str
    actual_status: str  # resolved / mitigated / persists / new_issue / insufficient_evidence
    labeled_by: str = ""
    note: str = ""


class MigrationAnswerRequest(BaseModel):
    answer_text: str = Field(min_length=1, max_length=20000)


# ---- 版本差异复审 ----

@router.post("/version-diff/run")
def run_version_diff(session_id: str, req: VersionDiffRequest):
    """版本差异复审:重新审查并与上一份报告对比(稳定身份+五态+修改理由对照)。"""
    try:
        return version_diff_service.run_version_diff(session_id, req.revision_note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/version-diff")
def get_latest_diff(session_id: str):
    """获取最近一次版本差异复审结果。"""
    result = version_diff_service.get_latest_diff(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="尚未进行版本差异复审")
    return result


@router.post("/version-diff/labels")
def add_manual_label(session_id: str, req: ManualLabelRequest):
    """添加人工复核标签(验证已解决精确率)。"""
    try:
        return version_diff_service.add_manual_label(
            session_id, req.comparison_id, req.actual_status, req.labeled_by, req.note
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/version-diff/stats")
def get_version_diff_stats(session_id: str):
    """版本差异复审统计:五态计数+已解决精确率+迁移表现。"""
    return version_diff_service.get_stats(session_id)


# ---- 学习迁移 ----

@router.post("/migration/generate")
def generate_migration_question(session_id: str):
    """根据原发现生成不同表面情境、同一方法要点的迁移题。"""
    from app.agent.agent_service import agent_service

    try:
        return agent_service.generate_migration_question(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/migration")
def list_migration_questions(session_id: str):
    """获取迁移题列表。"""
    from app.services.store import data_store

    try:
        store = data_store.require(session_id)
        return {"questions": store.migration_questions}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/migration/{question_id}/answer")
def answer_migration(session_id: str, question_id: str, req: MigrationAnswerRequest):
    """提交迁移题回答并评分(看推理过程)。"""
    from app.agent.agent_service import agent_service

    try:
        return agent_service.score_migration_answer(
            session_id, question_id, req.answer_text
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
