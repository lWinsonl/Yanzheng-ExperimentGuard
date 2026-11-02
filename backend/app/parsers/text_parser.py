"""纯文本/Markdown 解析器:直接以 UTF-8 解码,偏移即字符索引。"""

from __future__ import annotations

from app.parsers.base import ParserBase


class TextParser(ParserBase):
    def parse_content(self, raw: bytes, filename: str) -> tuple[str, bool, str]:
        try:
            content = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("文本不是UTF-8或带BOM的UTF-16，请重新另存为UTF-8后上传") from exc
        if "\x00" in content:
            raise ValueError("材料包含二进制内容，请选择受支持的文档格式")
        return content, False, ""
