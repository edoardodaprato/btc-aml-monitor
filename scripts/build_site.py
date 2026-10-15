"""Build site/guide.html from docs/GUIDE.md, so the website carries the full user guide.

The guide is written once, in Markdown. This script converts the small subset of
Markdown it uses (headings, paragraphs, lists, tables, code blocks, quotes, bold,
italic, inline code, links) without third-party libraries. A test fails if the
committed page is out of date.

Usage:
    python scripts/build_site.py
"""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "GUIDE.md"
OUTPUT = ROOT / "site" / "guide.html"

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


def render_blocks(lines: list[str]) -> str:
    """Convert Markdown lines to HTML block elements."""
    html: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif _FENCE.match(line):
            i = _code_block(lines, i, html)
        elif match := _HEADING.match(line):
            level, text = len(match.group(1)), match.group(2).strip()
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


def build_guide(markdown: str) -> str:
    """The complete guide page."""
    lines = markdown.splitlines()
    title = lines[0].lstrip("# ").strip()
    body = render_blocks(lines[1:])
    toc = "".join(
        f'<li><a href="#{slug(line[3:].strip())}">{inline(line[3:].strip())}</a></li>'
        for line in lines
        if line.startswith("## ")
    )
    return PAGE.format(title=escape(title), toc=toc, body=body)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>User guide · btc-aml-monitor</title>
<meta name="description" content="Step-by-step guide to btc-aml-monitor: installation, control panel, sanctions list, labels, rules in plain words, multi-hop exposure, block scan and limitations.">
<!-- Generated from docs/GUIDE.md by scripts/build_site.py. Do not edit by hand. -->
<style>
  :root {{
    --bg: #f7f8fa; --surface: #ffffff; --surface-2: #eef1f5; --text: #15191f;
    --muted: #5a6472; --border: #dde2e9; --accent: #c76a00; --accent-soft: #fff1df;
    --code-bg: #0f1720; --code-text: #e6edf3;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #0d1117; --surface: #151b23; --surface-2: #1c2430; --text: #e6edf3;
      --muted: #9aa5b4; --border: #2a3441; --accent: #f59e0b; --accent-soft: #2a1f0d;
      --code-bg: #0a0e14;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #0d1117; --surface: #151b23; --surface-2: #1c2430; --text: #e6edf3;
    --muted: #9aa5b4; --border: #2a3441; --accent: #f59e0b; --accent-soft: #2a1f0d;
    --code-bg: #0a0e14;
  }}
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  header {{
    position: sticky; top: 0; z-index: 10; border-bottom: 1px solid var(--border);
    background: color-mix(in srgb, var(--bg) 88%, transparent); backdrop-filter: blur(8px);
  }}
  header .bar {{ max-width: 1180px; margin: 0 auto; padding: 0 16px; height: 56px;
    display: flex; align-items: center; justify-content: space-between; gap: 16px; }}
  .brand {{ font-weight: 700; color: var(--text); }}
  .brand span {{ color: var(--accent); }}
  header nav a {{ color: var(--muted); font-size: 14px; margin-left: 18px; }}
  .layout {{ max-width: 1180px; margin: 0 auto; padding: 32px 16px 64px;
    display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 40px; }}
  aside {{ position: sticky; top: 80px; align-self: start; max-height: calc(100vh - 100px);
    overflow-y: auto; font-size: 14px; }}
  aside h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin: 0 0 10px; }}
  aside ol {{ list-style: none; padding: 0; margin: 0; }}
  aside li {{ margin: 0 0 8px; }}
  aside a {{ color: var(--muted); }}
  aside a:hover {{ color: var(--text); }}
  article {{ min-width: 0; max-width: 820px; }}
  article h1 {{ font-size: clamp(28px, 4vw, 38px); line-height: 1.15; margin: 0 0 8px; letter-spacing: -.02em; }}
  article h2 {{ font-size: 24px; margin: 48px 0 12px; padding-top: 24px; border-top: 1px solid var(--border); scroll-margin-top: 72px; }}
  article h3 {{ font-size: 18px; margin: 28px 0 8px; scroll-margin-top: 72px; }}
  article p, article li {{ color: var(--text); }}
  article .lead {{ color: var(--muted); font-size: 18px; }}
  code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .88em;
    background: var(--surface-2); padding: .1em .35em; border-radius: 4px; }}
  pre {{ background: var(--code-bg); color: var(--code-text); border-radius: 10px; padding: 16px;
    overflow-x: auto; font-size: 13.5px; line-height: 1.55; }}
  pre code {{ background: none; padding: 0; color: inherit; font-size: inherit; }}
  blockquote {{ margin: 16px 0; padding: 12px 16px; background: var(--accent-soft);
    border-left: 3px solid var(--accent); border-radius: 0 8px 8px 0; }}
  blockquote p {{ margin: 0; }}
  .table-wrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 10px;
    background: var(--surface); margin: 16px 0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14.5px; }}
  th, td {{ text-align: left; padding: 9px 14px; border-bottom: 1px solid var(--border); vertical-align: top; }}
  th {{ background: var(--surface-2); white-space: nowrap; }}
  tr:last-child td {{ border-bottom: 0; }}
  footer {{ border-top: 1px solid var(--border); padding: 24px 16px 40px; text-align: center;
    color: var(--muted); font-size: 14px; }}
  @media (max-width: 860px) {{
    .layout {{ grid-template-columns: 1fr; gap: 16px; padding-top: 20px; }}
    aside {{ position: static; max-height: none; background: var(--surface);
      border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }}
  }}
</style>
</head>
<body>
<header>
  <div class="bar">
    <a class="brand" href="index.html">btc-aml<span>-monitor</span></a>
    <nav><a href="index.html">← Overview</a><a href="https://github.com/edoardodaprato/btc-aml-monitor">GitHub</a></nav>
  </div>
</header>
<div class="layout">
  <aside>
    <h2>Contents</h2>
    <ol>{toc}</ol>
  </aside>
  <article>
    <h1>{title}</h1>
{body}
  </article>
</div>
<footer>Educational project, not a validated compliance solution. ·
  <a href="index.html">Overview</a> · <a href="https://github.com/edoardodaprato/btc-aml-monitor">Source code</a></footer>
</body>
</html>
"""


def main() -> None:
    OUTPUT.write_text(build_guide(GUIDE.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
