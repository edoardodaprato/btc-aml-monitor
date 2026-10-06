"""Shared pytest fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A writable copy of the project's default config folder."""
    target = tmp_path / "config"
    shutil.copytree(PROJECT_ROOT / "config", target)
    return target
