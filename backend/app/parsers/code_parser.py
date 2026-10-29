"""代码解析器。

骨架阶段直接返回源码文本(保留行结构与注释,行号可由偏移换算)。
Jupyter Notebook 提取各 cell 代码并拼接,cell 边界以分隔注释标记,
保证 SourceSpan 仍可回溯到拼接后文本。
"""

from __future__ import annotations

import json

from app.parsers.base import ParserBase


class CodeParser(ParserBase):
    def parse_content(self, raw: bytes, filename: str) -> tuple[str, bool, str]:
        text = raw.decode("utf-8", errors="replace")
        if filename.lower().endswith(".ipynb"):
            return self._parse_notebook(text), False, ""
        return text, False, ""

    @staticmethod
    def _parse_notebook(text: str) -> str:
        try:
            nb = json.loads(text)
        except json.JSONDecodeError:
            return text
        parts: list[str] = []
        for idx, cell in enumerate(nb.get("cells", [])):
            ctype = cell.get("cell_type", "code")
            src = "".join(cell.get("source", []))
            parts.append(f"# === notebook cell {idx} ({ctype}) ===\n{src}")
        return "\n\n".join(parts)