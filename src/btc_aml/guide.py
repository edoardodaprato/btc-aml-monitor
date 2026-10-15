"""The user guide (docs/GUIDE.md) as HTML, for the website and the control panel.

The guide is written once, in Markdown. This module converts the small subset of
Markdown it uses (headings, paragraphs, lists, tables, code blocks, quotes, bold,
italic, inline code, links) without third-party libraries, so the website and the
control panel always show the same text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from pathlib import Path

GUIDE_PATH = Path(__file__).resolve().parents[2] / "docs" / "GUIDE.md"

_FENCE = re.compile(r"^(\s*)```")
_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
_LIST_ITEM = re.compile(r"^(\d+\.|-)\s+(.*)$")


def inline(text: str) -> str:
    """Escape ``text`` and apply code spans, links, bold and italic."""
    spans: list[str] = []

    def keep_code(match: re.Match[str]) -> str:
        spans.append(f"<code>{escape(match.group(1))}</code>")
        return f"\x00{len(spans) - 1}\x00"

    text = re.sub(r"`([^`]+)`", keep_code, text)
    text = escape(text, quote=False)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda m: f'<a href="{escape(m.group(2))}">{m.group(1)}</a>',
        text,
    )
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def render_blocks(lines: list[str], heading_offset: int = 0) -> str:
    """Convert Markdown lines to HTML; ``heading_offset`` demotes headings (## -> h3...)."""
    html: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif _FENCE.match(line):
            i = _code_block(lines, i, html)
        elif match := _HEADING.match(line):
            level, text = len(match.group(1)) + heading_offset, match.group(2).strip()
            html.append(f'<h{level} id="{slug(text)}">{inline(text)}</h{level}>')
            i += 1
        elif line.startswith("|"):
            i = _table(lines, i, html)
        elif line.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i].lstrip(">").strip())
                i += 1
            html.append(f"<blockquote><p>{inline(' '.join(quote))}</p></blockquote>")
        elif _LIST_ITEM.match(line):
            i = _list(lines, i, html)
        else:
            paragraph = []
            while i < len(lines) and lines[i].strip() and not _starts_block(lines[i]):
                paragraph.append(lines[i].strip())
                i += 1
            html.append(f"<p>{inline(' '.join(paragraph))}</p>")
    return "\n".join(html)


def _starts_block(line: str) -> bool:
    return bool(
        _FENCE.match(line)
        or _HEADING.match(line)
        or line.startswith(("|", ">"))
        or _LIST_ITEM.match(line)
    )


def _code_block(lines: list[str], i: int, html: list[str]) -> int:
    indent = len(_FENCE.match(lines[i]).group(1))  # type: ignore[union-attr]
    code = []
    i += 1
    while i < len(lines) and not _FENCE.match(lines[i]):
        code.append(lines[i][indent:])
        i += 1
    html.append(f"<pre><code>{escape(chr(10).join(code))}</code></pre>")
    return i + 1


def _table(lines: list[str], i: int, html: list[str]) -> int:
    rows = []
    while i < len(lines) and lines[i].startswith("|"):
        rows.append([cell.strip() for cell in lines[i].strip().strip("|").split("|")])
        i += 1
    header, body = rows[0], rows[2:]  # rows[1] is the |---| separator
    head = "".join(f"<th>{inline(cell)}</th>" for cell in header)
    rows_html = "".join(
        "<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>" for row in body
    )
    html.append(
        f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{rows_html}</tbody></table></div>"
    )
    return i


def _list(lines: list[str], i: int, html: list[str]) -> int:
    ordered = lines[i][0].isdigit()
    items: list[list[str]] = []
    while i < len(lines):
        match = _LIST_ITEM.match(lines[i])
        if match and lines[i][0].isdigit() == ordered:
            items.append([match.group(2)])
            i += 1
        elif lines[i].startswith("  ") and items:
            items[-1].append(_dedent(lines[i]))
            i += 1
        elif not lines[i].strip() and i + 1 < len(lines) and lines[i + 1].startswith("  "):
            items[-1].append("")
            i += 1
        else:
            break
    tag = "ol" if ordered else "ul"
    rendered = []
    for item in items:
        body = render_blocks(item)
        if body.startswith("<p>") and body.count("<p>") == 1 and body.endswith("</p>"):
            body = body[3:-4]  # a one-paragraph item needs no <p>
        rendered.append(f"<li>{body}</li>")
    html.append(f"<{tag}>{''.join(rendered)}</{tag}>")
    return i


def _dedent(line: str) -> str:
    return line[3:] if line.startswith("   ") else line[2:]


@dataclass(frozen=True)
class GuideHtml:
    title: str
    toc: list[tuple[str, str]]  # (anchor id, section title as HTML)
    body: str


def guide_html(markdown: str, heading_offset: int = 0) -> GuideHtml:
    """Title, table of contents (level-2 sections) and body of the guide."""
    lines = markdown.splitlines()
    title = lines[0].lstrip("# ").strip()
    toc = [
        (slug(line[3:].strip()), inline(line[3:].strip()))
        for line in lines
        if line.startswith("## ")
    ]
    return GuideHtml(title, toc, render_blocks(lines[1:], heading_offset))
