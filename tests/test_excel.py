"""Tests for the dependency-free Excel writer."""

from __future__ import annotations

import io
import zipfile

from btc_aml.reports.excel import Sheet, _column, workbook_bytes


def sheet_xml(data: bytes, index: int = 1) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as workbook:
        return workbook.read(f"xl/worksheets/sheet{index}.xml").decode()


def test_numbers_become_numbers_and_identifiers_stay_text() -> None:
    xml = sheet_xml(
        workbook_bytes([Sheet("T", ("a", "b", "c", "d"), [("42", "0.125", "007", "1" * 20)])])
    )
    assert '<c r="A2"><v>42</v></c>' in xml
    assert '<c r="B2"><v>0.125</v></c>' in xml
    assert '<t xml:space="preserve">007</t>' in xml  # leading zeros kept
    assert "1" * 20 + "</t>" in xml  # long digit strings are not rounded by Excel


def test_text_is_escaped_and_sheet_names_are_valid() -> None:
    data = workbook_bytes([Sheet("a/b:c", ("x",), [("<b>&\x01",)]), Sheet("A-B-C", ("x",), [])])
    assert "&lt;b&gt;&amp;" in sheet_xml(data)
    with zipfile.ZipFile(io.BytesIO(data)) as workbook:
        names = workbook.read("xl/workbook.xml").decode()
    assert 'name="a-b-c"' in names and 'name="A-B-C 2"' in names


def test_column_letters() -> None:
    assert [_column(i) for i in (0, 25, 26, 27, 701, 702)] == ["A", "Z", "AA", "AB", "ZZ", "AAA"]
