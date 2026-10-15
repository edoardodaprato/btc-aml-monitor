"""The website's guide page must match docs/GUIDE.md, and the converter must handle its Markdown."""

from __future__ import annotations

import importlib.util

from tests.conftest import PROJECT_ROOT

_spec = importlib.util.spec_from_file_location(
    "build_site", PROJECT_ROOT / "scripts" / "build_site.py"
)
build_site = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(build_site)  # type: ignore[union-attr]


def test_guide_page_is_up_to_date() -> None:
    expected = build_site.build_guide((PROJECT_ROOT / "docs" / "GUIDE.md").read_text())
    actual = (PROJECT_ROOT / "site" / "guide.html").read_text()
    assert actual == expected, "Run: python scripts/build_site.py"


def test_markdown_subset() -> None:
    html = build_site.render_blocks(
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
        ]
    )
    assert '<h2 id="1-title">1. Title</h2>' in html
    assert "<strong>bold</strong>" in html and "<em>italic</em>" in html
    assert "<code>a&lt;b&gt;</code>" in html
    assert '<a href="https://x.org">a link</a>' in html
    assert "<th>A</th>" in html and "<td>2</td>" in html
    assert "<li>First item continues here.</li>" in html
    assert "<pre><code>echo hi</code></pre>" in html
    assert "<blockquote><p>A note</p></blockquote>" in html
