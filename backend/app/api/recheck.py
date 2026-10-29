"""复查路由:修改后复查,比较前后版本。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import recheck_service

router = APIRouter(prefix="/api/sessions/{session_id}/recheck", tags=["recheck"])


class RecheckRequest(BaseModel):
    revision_note: str = ""


@router.post("/run")
def run_recheck(session_id: str, req: RecheckRequest):
    """复查:重新审查并与上一份报告对比,显示已解除/仍待核实的疑点。"""
    try:
        result = recheck_service.run_recheck(session_id, req.revision_note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result