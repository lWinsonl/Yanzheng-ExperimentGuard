"""材料路由:收集材料(上传文件或粘贴文本,标记计划/执行)。"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.services import evidence_chain

router = APIRouter(prefix="/api/sessions/{session_id}/materials", tags=["materials"])


@router.post("/upload")
async def upload_material(
    session_id: str,
    role: str = Form(...),
    mode: str = Form("append"),
    file: UploadFile = File(...),
):
    """上传文件材料。role 为 plan 或 execution;mode 为 append(补充)或 replace(替换旧版本)。"""
    try:
        raw = await file.read(5 * 1024 * 1024 + 1)
        if len(raw) > 5 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="单个文件不能超过 5 MB")
        if not raw:
            raise HTTPException(status_code=400, detail="文件为空，请选择包含文字或代码的材料")
        doc, facts, dropped = evidence_chain.ingest_material(
            session_id, raw, file.filename or "unnamed", role
        )
        if mode == "replace":
            evidence_chain.clear_materials(session_id, role, keep_material_id=doc.material_id)
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
    content: str = Field(min_length=1, max_length=100000)
    mode: str = "append"  # append(补充) / replace(替换旧版本)


@router.post("/text")
def add_text_material(session_id: str, req: TextMaterialRequest):
    """粘贴文本材料(实验计划、代码片段等)。mode 为 append 或 replace。"""
    try:
        doc, facts, dropped = evidence_chain.extract_from_text(
            session_id, req.content, req.filename, req.role
        )
        if req.mode == "replace":
            evidence_chain.clear_materials(session_id, req.role, keep_material_id=doc.material_id)
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
