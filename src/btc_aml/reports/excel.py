"""Write a small Excel workbook (.xlsx) with the standard library only.

An .xlsx file is a zip of XML documents. This module writes the minimum Excel needs:
one sheet per table, a bold frozen header row with filters, and sensible column widths.
Short numeric values are stored as numbers so they sort and sum in Excel; long digit
strings and anything else (addresses, transaction ids) stay text, so nothing is altered.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from xml.sax.saxutils import escape

NUMBER = re.compile(r"^-?\d{1,12}(\.\d{1,10})?$")
ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
SHEET_NAME_BAD = re.compile(r"[\[\]:*?/\\]")
MAX_WIDTH = 60


@dataclass
class Sheet:
    name: str
    header: Sequence[str]
    rows: Sequence[Sequence[object]]


def workbook_bytes(sheets: Sequence[Sheet]) -> bytes:
    """The .xlsx file containing these sheets, in order."""
    names = _unique_names([s.name for s in sheets])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types(len(sheets)))
        zf.writestr("_rels/.rels", _ROOT_RELS)
        zf.writestr("xl/workbook.xml", _workbook(names))
        zf.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(sheets)))
        zf.writestr("xl/styles.xml", _STYLES)
        for index, sheet in enumerate(sheets, start=1):
            zf.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(sheet))
    return buffer.getvalue()


def _sheet_xml(sheet: Sheet) -> str:
    rows = [list(sheet.header), *[list(r) for r in sheet.rows]]
    columns = max((len(r) for r in rows), default=1) or 1
    widths = [10] * columns
    body = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            text = "" if value is None else str(value)
            widths[c] = min(MAX_WIDTH, max(widths[c], len(text) + 2))
            ref = f"{_column(c)}{r}"
            if r == 1:
                cells.append(f'<c r="{ref}" t="inlineStr" s="1"><is><t>{_text(text)}</t></is></c>')
            elif (
                text
                and NUMBER.match(text)
                and not (len(text) > 1 and text[0] == "0" and text[1] != ".")
            ):
                cells.append(f'<c r="{ref}"><v>{text}</v></c>')
            elif text:
                cells.append(
                    f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_text(text)}</t></is></c>'
                )
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    last = f"{_column(columns - 1)}{max(len(rows), 1)}"
    cols = "".join(
        f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"<cols>{cols}</cols><sheetData>{''.join(body)}</sheetData>"
        f'<autoFilter ref="A1:{last}"/></worksheet>'
    )


def _column(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def _text(value: str) -> str:
    return escape(ILLEGAL_XML.sub("", value))


def _unique_names(names: list[str]) -> list[str]:
    result: list[str] = []
    for name in names:
        clean = SHEET_NAME_BAD.sub("-", name)[:31] or "Sheet"
        candidate, n = clean, 2
        while candidate.lower() in (r.lower() for r in result):
            candidate, n = f"{clean[:28]} {n}", n + 1
        result.append(candidate)
    return result


def _content_types(count: int) -> str:
    sheets = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f"{sheets}</Types>"
    )


def _workbook(names: list[str]) -> str:
    sheets = "".join(
        f'<sheet name="{escape(n, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>'
        for i, n in enumerate(names, 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets></workbook>"
    )


def _workbook_rels(count: int) -> str:
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/'
        f'2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, count + 1)
    )
    styles = (
        f'<Relationship Id="rId{count + 1}" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{rels}{styles}</Relationships>"
    )


_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
)

_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="3"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFE8EEF4"/></patternFill></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
    "</cellXfs>"
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)
