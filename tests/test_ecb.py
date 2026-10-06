"""Tests for the ECB EUR/USD reference rates (offline, real rows)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx
import pytest

from btc_aml.data_sources.ecb import FxError, load_ecb_rates, update_ecb_rates

# Excerpt of the official eurofxref-hist.csv (first columns only).
ECB_CSV = """Date,USD,JPY,CYP
2022-04-25,1.0746,138.1,N/A
2022-04-22,1.0817,139.03,N/A
2008-01-02,1.4717,163.55,0.585274
"""


def zipped(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("eurofxref-hist.csv", text)
    return buffer.getvalue()


def serve(body: bytes) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, content=body))


def test_update_keeps_usd_column_and_reloads(tmp_path: Path) -> None:
    target = tmp_path / "fx.json"

    saved = update_ecb_rates("https://ecb.test/hist.zip", target, serve(zipped(ECB_CSV)))

    assert saved.usd_per_eur == {"2022-04-25": 1.0746, "2022-04-22": 1.0817, "2008-01-02": 1.4717}
    assert load_ecb_rates(target) == saved
    assert saved.version.startswith("ECB EUR/USD up to 2022-04-25")


def test_missing_file_means_no_rates(tmp_path: Path) -> None:
    assert load_ecb_rates(tmp_path / "missing.json") is None


def test_invalid_archive_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FxError, match="Invalid ECB archive"):
        update_ecb_rates("https://ecb.test/hist.zip", tmp_path / "fx.json", serve(b"not a zip"))
