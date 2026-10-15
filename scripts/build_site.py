"""Build the website (site/index.html) from its template and the user guide.

The website is a single page: the overview written in ``scripts/site_template.html``
with the full user guide (docs/GUIDE.md) inserted where the template says
``<!-- GUIDE -->``. ``site/guide.html``, the guide's former address, now redirects to
that section. A test fails if the committed pages are out of date.

Usage:
    python scripts/build_site.py
"""

from __future__ import annotations

from pathlib import Path

from btc_aml.guide import GUIDE_PATH, guide_html

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "scripts" / "site_template.html"
INDEX = ROOT / "site" / "index.html"
GUIDE_REDIRECT = ROOT / "site" / "guide.html"
PLACEHOLDER = "<!-- GUIDE -->"

SECTION = """  <section id="guide">
    <div class="wrap">
      <h2>User guide</h2>
      <p class="sub">Everything needed to install the tool, run analyses and review the results, step by
        step and for readers starting from scratch. The tool runs on your own computer, not on this
        website.</p>
      <div class="guide-layout">
        <aside class="guide-toc">
          <div class="toc-title">Contents</div>
          <ol>{toc}</ol>
        </aside>
        <article class="guide">
<!-- Generated from docs/GUIDE.md by scripts/build_site.py. Edit the guide, not this page. -->
{body}
        </article>
      </div>
    </div>
  </section>
"""

REDIRECT = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Tracery user guide</title>
<meta http-equiv="refresh" content="0; url=index.html#guide">
<link rel="canonical" href="index.html#guide">
</head>
<body>
<p>The user guide has moved to <a href="index.html#guide">the main page</a>.</p>
</body>
</html>
"""


def build_index(template: str, guide_markdown: str) -> str:
    guide = guide_html(guide_markdown, heading_offset=1)  # guide sections become <h3>
    toc = "".join(f'<li><a href="#{anchor}">{title}</a></li>' for anchor, title in guide.toc)
    return template.replace(PLACEHOLDER, SECTION.format(toc=toc, body=guide.body))


def build_pages() -> dict[Path, str]:
    """Every generated page and its content."""
    index = build_index(
        TEMPLATE.read_text(encoding="utf-8"), GUIDE_PATH.read_text(encoding="utf-8")
    )
    return {INDEX: index, GUIDE_REDIRECT: REDIRECT}


def main() -> None:
    for path, content in build_pages().items():
        path.write_text(content, encoding="utf-8")
        print(f"Wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
