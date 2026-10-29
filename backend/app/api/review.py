"""审查路由:运行审查、获取报告。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services import review_service

router = APIRouter(prefix="/api/sessions/{session_id}/review", tags=["review"])


@router.post("/run")
def run_review(session_id: str):
    """运行审查:基于已确认事实执行学科规则,生成报告。"""
    try:
        report = review_service.run_review(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return report


@router.get("/latest")
def latest_report(session_id: str):
    """获取最近一次审查报告。"""
    report = review_service.latest_report(session_id)
    if report is None:
        raise HTTPException(status_code=404, detail="尚无审查报告")
    return report


@router.get("/reports/{report_id}")
def get_report(session_id: str, report_id: str):
    report = review_service.get_report(session_id, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return report