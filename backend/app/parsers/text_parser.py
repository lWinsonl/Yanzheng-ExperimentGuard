"""纯文本/Markdown 解析器:直接以 UTF-8 解码,偏移即字符索引。"""

from __future__ import annotations

from app.parsers.base import ParserBase


class TextParser(ParserBase):
    def parse_content(self, raw: bytes, filename: str) -> tuple[str, bool, str]:
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            content = raw.decode("utf-8", errors="replace")
        return content, False, ""