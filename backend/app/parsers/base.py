"""文档解析器。

统一输出 ParsedDocument:纯文本 content + 字符偏移体系,
使后续所有 SourceSpan 都能回溯到原文。

PDF 扫描件、图片、复杂表格不假装普通文字提取已覆盖:
- PDF:尝试文本层提取;若某页无文本层,置 ocr_required=True 并在 ocr_note 说明。
- 图片/扫描件:直接置 ocr_required=True,content 为空。
"""

from __future__ import annotations

from app.models.evidence import MaterialKind, MaterialRole, ParsedDocument, new_id

# 扩展名 -> MaterialKind 映射
EXT_KIND_MAP: dict[str, MaterialKind] = {
    ".txt": MaterialKind.TEXT,
    ".md": MaterialKind.TEXT,
    ".markdown": MaterialKind.TEXT,
    ".py": MaterialKind.CODE,
    ".ipynb": MaterialKind.CODE,
    ".js": MaterialKind.CODE,
    ".ts": MaterialKind.CODE,
    ".java": MaterialKind.CODE,
    ".go": MaterialKind.CODE,
    ".rs": MaterialKind.CODE,
    ".sh": MaterialKind.CODE,
    ".json": MaterialKind.CONFIG,
    ".yaml": MaterialKind.CONFIG,
    ".yml": MaterialKind.CONFIG,
    ".toml": MaterialKind.CONFIG,
    ".ini": MaterialKind.CONFIG,
    ".csv": MaterialKind.RESULT,
    ".log": MaterialKind.RESULT,
    ".pdf": MaterialKind.PDF,
}


def guess_kind(filename: str) -> MaterialKind:
    """根据扩展名推断材料类型。"""
    lower = filename.lower()
    for ext, kind in EXT_KIND_MAP.items():
        if lower.endswith(ext):
            return kind
    return MaterialKind.TEXT


def make_span_snippet(content: str, start: int, end: int) -> str:
    """从 content 截取片段,供 SourceSpan 使用。越界时自动夹紧。"""
    start = max(0, min(start, len(content)))
    end = max(start, min(end, len(content)))
    return content[start:end]


class ParserBase:
    """解析器基类。子类实现 parse_content。"""

    def parse_content(self, raw: bytes, filename: str) -> tuple[str, bool, str]:
        """返回 (content, ocr_required, ocr_note)。"""
        raise NotImplementedError

    def parse(
        self,
        raw: bytes,
        filename: str,
        role: MaterialRole,
        material_id: str | None = None,
    ) -> ParsedDocument:
        content, ocr_required, ocr_note = self.parse_content(raw, filename)
        return ParsedDocument(
            material_id=material_id or new_id("mat"),
            role=role,
            kind=guess_kind(filename),
            filename=filename,
            content=content,
            ocr_required=ocr_required,
            ocr_note=ocr_note,
        )


def get_parser(kind: MaterialKind) -> ParserBase:
    """根据材料类型选择解析器。延迟导入避免可选依赖缺失时崩溃。"""
    if kind == MaterialKind.PDF:
        from app.parsers.pdf_parser import PdfParser

        return PdfParser()
    if kind == MaterialKind.CODE:
        from app.parsers.code_parser import CodeParser

        return CodeParser()
    from app.parsers.text_parser import TextParser

    return TextParser()