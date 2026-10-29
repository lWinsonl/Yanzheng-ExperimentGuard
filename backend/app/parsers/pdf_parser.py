"""PDF 解析器。

原则:不假装普通文字提取已覆盖扫描件。
- 有文本层:提取拼接为 content(页间加分页标记)。
- 无文本层或提取为空:置 ocr_required=True,ocr_note 说明缺口,
  审查时相关事实只能标为"信息不足"。
- pypdf 未安装时:整体标为 ocr_required,不抛异常阻断流程。
"""

from __future__ import annotations

from app.parsers.base import ParserBase


class PdfParser(ParserBase):
    def parse_content(self, raw: bytes, filename: str) -> tuple[str, bool, str]:
        try:
            from pypdf import PdfReader
        except ImportError:
            return (
                "",
                True,
                "服务端未安装 pypdf,PDF 内容未提取。请安装依赖或改用文本/代码材料。",
            )

        try:
            import io

            reader = PdfReader(io.BytesIO(raw))
        except Exception as exc:  # noqa: BLE001
            return "", True, f"PDF 解析失败:{exc}。可能需要 OCR。"

        pages_text: list[str] = []
        empty_pages: list[int] = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                t = page.extract_text() or ""
            except Exception:  # noqa: BLE001
                t = ""
            t = t.strip()
            if not t:
                empty_pages.append(i)
            else:
                pages_text.append(f"--- PDF 第 {i} 页 ---\n{t}")

        content = "\n\n".join(pages_text)
        ocr_required = len(empty_pages) > 0 or not content
        note = ""
        if empty_pages:
            note = f"第 {', '.join(map(str, empty_pages))} 页无可提取文本(可能为扫描件/图片),需 OCR。"
        return content, ocr_required, note