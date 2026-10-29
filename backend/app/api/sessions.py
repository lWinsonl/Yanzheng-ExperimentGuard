"""会话路由:确定审查范围(实验类型 + 研究主张)。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import data_store, evidence_chain

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    title: str = ""
    experiment_type: str = "data_model"
    claims: list[str] = []


@router.post("")
def create_session(req: CreateSessionRequest):
    session = evidence_chain.create_session(req.title, req.experiment_type, req.claims)
    return session


@router.get("")
def list_sessions():
    return data_store.all_sessions()


@router.get("/{session_id}")
def get_session(session_id: str):
    store = data_store.get(session_id)
    if store is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return store.session


@router.get("/{session_id}/materials")
def list_materials(session_id: str):
    store = data_store.get(session_id)
    if store is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    # 返回文档元信息(不含全文,前端按需拉取)
    return [
        {
            "material_id": d.material_id,
            "role": d.role.value,
            "kind": d.kind.value,
            "filename": d.filename,
            "content_length": len(d.content),
            "ocr_required": d.ocr_required,
            "ocr_note": d.ocr_note,
        }
        for d in store.docs.values()
    ]


@router.get("/{session_id}/materials/{material_id}")
def get_material_content(session_id: str, material_id: str):
    """返回文档全文,供前端高亮原文片段(SourceSpan 定位)。"""
    store = data_store.get(session_id)
    if store is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    doc = store.docs.get(material_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="材料不存在")
    return doc