"""材料路由:收集材料(上传文件或粘贴文本,标记计划/执行)。"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.services import evidence_chain

router = APIRouter(prefix="/api/sessions/{session_id}/materials", tags=["materials"])


@router.post("/upload")
async def upload_material(
    session_id: str,
    role: str = Form(...),
    file: UploadFile = File(...),
):
    """上传文件材料。role 为 plan 或 execution。"""
    try:
        raw = await file.read()
        doc, facts, dropped = evidence_chain.ingest_material(
            session_id, raw, file.filename or "unnamed", role
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "material_id": doc.material_id,
        "filename": doc.filename,
        "role": doc.role.value,
        "kind": doc.kind.value,
        "ocr_required": doc.ocr_required,
        "ocr_note": doc.ocr_note,
        "extracted_facts": facts,
        "dropped": dropped,
    }


class TextMaterialRequest(BaseModel):
    role: str
    filename: str
    content: str


@router.post("/text")
def add_text_material(session_id: str, req: TextMaterialRequest):
    """粘贴文本材料(实验计划、代码片段等)。"""
    try:
        doc, facts, dropped = evidence_chain.extract_from_text(
            session_id, req.content, req.filename, req.role
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "material_id": doc.material_id,
        "filename": doc.filename,
        "role": doc.role.value,
        "kind": doc.kind.value,
        "ocr_required": doc.ocr_required,
        "ocr_note": doc.ocr_note,
        "extracted_facts": facts,
        "dropped": dropped,
    }