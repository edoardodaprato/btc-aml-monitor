"""Guard rail: no local data, outputs or secrets may ever be tracked by git.

Runs locally and in CI on every push, so a mistake is caught before it lingers.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from tests.conftest import PROJECT_ROOT

FORBIDDEN = [
    r"(^|/)\.env(\.|$)",
    r"\.(key|pem|p12|sqlite3?|db)$",
    r"(^|/)secrets?/",
    r"^\.venv/",
    r"^data/(cache|ofac|fx)/",
    r"^data/labels\.csv$",
    r"^output/",
    r"\.log$",
]


def tracked_files() -> list[str]:
    if shutil.which("git") is None or not (PROJECT_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    result = subprocess.run(
        ["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.splitlines()


def test_no_local_data_outputs_or_secrets_are_tracked() -> None:
    offending = [
        path for path in tracked_files() if any(re.search(rule, path) for rule in FORBIDDEN)
    ]
    assert offending == []
