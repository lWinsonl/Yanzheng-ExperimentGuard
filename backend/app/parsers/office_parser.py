"""Bounded read-only OOXML text extraction; never extracts ZIP entries to disk."""
from __future__ import annotations

import csv
import io
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET

from app.parsers.base import ParserBase

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def xml(archive, name):
    raw = archive.read(name)
    scan = raw.upper().replace(b"\x00", b"")
    if b"<!DOCTYPE" in scan or b"<!ENTITY" in scan:
        raise ValueError("材料包含不支持的XML实体声明，请导出为普通文本")
    return ET.fromstring(raw)


class OfficeParser(ParserBase):
    def parse_content(self, raw, filename):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                info = archive.infolist()
                names = [part.filename for part in info]
                if (len(info) > 500 or len(set(names)) != len(names)
                        or sum(p.file_size for p in info) > 20 * 1024 * 1024
                        or any(p.file_size > 5 * 1024 * 1024 or p.flag_bits & 1 for p in info)):
                    raise ValueError("Office材料解压后过大、包含重复部件或已加密，请拆分或导出文本")
                if any(name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/") for name in names):
                    raise ValueError("Office材料包含非法内部路径")
                if "[Content_Types].xml" not in names:
                    raise ValueError("不是完整的DOCX/XLSX文件，请从Office重新另存为")
                if filename.lower().endswith(".docx"):
                    return self._word(archive)
                return self._sheets(archive)
        except (zipfile.BadZipFile, KeyError, ET.ParseError, RuntimeError, NotImplementedError) as exc:
            raise ValueError("Office材料损坏、加密或格式不受支持，请重新导出") from exc

    def _word(self, archive):
        root = xml(archive, "word/document.xml")
        body = root.find(W + "body")
        if body is None:
            raise ValueError("DOCX没有可读取的正文")

        def paragraph(node):
            text = []
            for item in node.iter():
                if item.tag == W + "t":
                    text.append(item.text or "")
                elif item.tag == W + "tab":
                    text.append("\t")
                elif item.tag in (W + "br", W + "cr"):
                    text.append("\n")
            return "".join(text)

        lines = []
        for block in body:
            if block.tag == W + "p":
                lines.append(paragraph(block))
            elif block.tag == W + "tbl":
                for row in block.findall(W + "tr"):
                    lines.append("\t".join(" ".join(paragraph(p) for p in cell.findall(W + "p"))
                                           for cell in row.findall(W + "tc")))
        content = "\n".join(lines).strip()
        partial = any(n.tag in (W + "drawing", W + "object", W + "pict", W + "altChunk", W + "sdt") for n in root.iter())
        partial |= any("header" in name or "footer" in name or "footnotes" in name or "endnotes" in name for name in archive.namelist())
        return content, partial or not content, ("仅提取正文和表格文字；图像、嵌入对象、页眉页脚及特殊内容未核对。" if partial else "未提取到正文文字" if not content else "")

    def _sheets(self, archive):
        workbook = xml(archive, "xl/workbook.xml")
        rels = xml(archive, "xl/_rels/workbook.xml.rels")
        targets = {r.attrib["Id"]: r.attrib.get("Target", "") for r in rels
                   if r.attrib.get("TargetMode") != "External"}
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(si.itertext()) for si in xml(archive, "xl/sharedStrings.xml")]
        lines, partial, count = [], False, 0
        for sheet in workbook.findall(S + "sheets/" + S + "sheet"):
            target = targets.get(sheet.attrib.get(R + "id", ""), "")
            path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
            if not path.startswith("xl/worksheets/") or path not in archive.namelist():
                partial = True
                continue
            rows = xml(archive, path)
            output = io.StringIO()
            writer = csv.writer(output, lineterminator="\n")
            for row in rows.findall(S + "sheetData/" + S + "row"):
                values = {}
                for cell in row.findall(S + "c"):
                    count += 1
                    if count > 20000:
                        raise ValueError("工作簿超过20000个单元格，请分表上传")
                    ref = cell.attrib.get("r", "")
                    match = re.fullmatch(r"([A-Z]{1,3})\d+", ref)
                    if not match:
                        partial = True
                        continue
                    col = 0
                    for char in match[1]:
                        col = col * 26 + ord(char) - 64
                    if col > 256:
                        raise ValueError("工作簿超过256列，请先精简材料")
                    value = cell.findtext(S + "v", "")
                    if cell.attrib.get("t") == "s":
                        try:
                            value = strings[int(value)] if int(value) >= 0 else ""
                        except (ValueError, IndexError):
                            value, partial = "", True
                    elif cell.attrib.get("t") == "inlineStr":
                        value = "".join(cell.find(S + "is").itertext()) if cell.find(S + "is") is not None else ""
                    if cell.find(S + "f") is not None:
                        # Do not trust cached formula values or execute formulas / links.
                        value, partial = "[公式未计算]", True
                    if cell.attrib.get("t") in ("e", "d"):
                        partial = True
                    values[col] = value
                writer.writerow([values.get(i, "") for i in range(1, max(values, default=0) + 1)])
            lines.append(f"--- 工作表：{sheet.attrib.get('name', '')} ---\n" + output.getvalue())
        partial |= any(name.startswith(("xl/charts/", "xl/drawings/", "xl/externalLinks/")) for name in archive.namelist())
        content = "\n".join(lines).strip()
        return content, partial or not content, ("公式未执行；图表、图片、外部链接或部分特殊单元格未解析。" if partial else "未提取到工作表文字" if not content else "")
