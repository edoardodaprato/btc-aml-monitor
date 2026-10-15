"""The website must match its template and docs/GUIDE.md; the guide converter must work."""

from __future__ import annotations

import importlib.util

from btc_aml.guide import guide_html, render_blocks
from tests.conftest import PROJECT_ROOT

_spec = importlib.util.spec_from_file_location(
    "build_site", PROJECT_ROOT / "scripts" / "build_site.py"
)
build_site = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(build_site)  # type: ignore[union-attr]


def test_website_pages_are_up_to_date() -> None:
    for path, expected in build_site.build_pages().items():
        assert path.read_text() == expected, "Run: python scripts/build_site.py"


def test_website_is_one_page_with_the_guide() -> None:
    index = (PROJECT_ROOT / "site" / "index.html").read_text()
    assert 'id="guide"' in index
    assert 'id="7-the-rules-in-plain-words"' in index
    assert "index.html#guide" in (PROJECT_ROOT / "site" / "guide.html").read_text()


def test_guide_table_of_contents() -> None:
    guide = guide_html("# Title\n\nIntro.\n\n## 1. First\n\nText.\n\n## 2. Second\n")
    assert guide.title == "Title"
    assert [anchor for anchor, _ in guide.toc] == ["1-first", "2-second"]


def test_markdown_subset() -> None:
    html = render_blocks(
        [
            "## 1. Title",
            "Text with **bold**, *italic*, `a<b>` and [a link](https://x.org).",
            "",
            "| A | B |",
            "|---|---|",
            "| 1 | 2 |",
            "",
            "1. First item",
            "   continues here.",
            "2. Second:",
            "",
            "   ```bash",
            "   echo hi",
            "   ```",
            "",
            "> A note",
        ],
        heading_offset=1,
    )
    assert '<h3 id="1-title">1. Title</h3>' in html
    assert "<strong>bold</strong>" in html and "<em>italic</em>" in html
    assert "<code>a&lt;b&gt;</code>" in html
    assert '<a href="https://x.org">a link</a>' in html
    assert "<th>A</th>" in html and "<td>2</td>" in html
    assert "<li>First item continues here.</li>" in html
    assert "<pre><code>echo hi</code></pre>" in html
    assert "<blockquote><p>A note</p></blockquote>" in html
