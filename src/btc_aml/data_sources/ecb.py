"""ECB euro foreign exchange reference rates (EUR/USD), used to fill EUR price gaps.

mempool.space sometimes has a BTC price in USD but not in EUR for a given day (it
answers EUR = -1). In that case the EUR price is derived as ``USD price / EUR-USD
rate``, using the official ECB reference rate of that day, or of the latest ECB
business day before it (no fixing on weekends and TARGET holidays).

The ECB publishes the full history since 1999 as a zipped CSV; we keep only the USD
column, with the download date and a SHA-256 for the audit trail.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

DOWNLOAD_TIMEOUT_SECONDS = 60
MAX_RATE_AGE_DAYS = 7  # longest gap between ECB fixings (e.g. Easter) is 4 days


class FxError(RuntimeError):
    """The ECB rates could not be downloaded, parsed or loaded."""


@dataclass(frozen=True)
class EcbRates:
    usd_per_eur: dict[str, float]  # ISO date -> USD for 1 EUR
    downloaded_at: str
    sha256: str
    source_url: str

    @property
    def version(self) -> str:
        latest = max(self.usd_per_eur) if self.usd_per_eur else "empty"
        return f"ECB EUR/USD up to {latest} / sha256:{self.sha256[:12]}"

    def rate_on(self, day: date) -> tuple[float, str] | None:
        """(USD per EUR, rate date) for ``day`` or the latest fixing before it."""
        for back in range(MAX_RATE_AGE_DAYS + 1):
            key = (day - timedelta(days=back)).isoformat()
            if key in self.usd_per_eur:
                return self.usd_per_eur[key], key
        return None


def update_ecb_rates(
    url: str, target: Path, transport: httpx.BaseTransport | None = None
) -> EcbRates:
    """Download the ECB history, keep the USD column and save it as JSON."""
    try:
        with httpx.Client(
            transport=transport, timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise FxError(f"Could not download ECB rates from {url}: {exc}") from exc

    rates = EcbRates(
        usd_per_eur=parse_ecb_zip(response.content),
        downloaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
        sha256=hashlib.sha256(response.content).hexdigest(),
        source_url=url,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rates.__dict__, indent=1, sort_keys=True), encoding="utf-8")
    return rates


def load_ecb_rates(path: Path) -> EcbRates | None:
    """Load saved rates; None if ``btc-aml update-fx`` was never run."""
    if not path.is_file():
        return None
    return EcbRates(**json.loads(path.read_text(encoding="utf-8")))


def parse_ecb_zip(content: bytes) -> dict[str, float]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            text = archive.read(archive.namelist()[0]).decode("utf-8")
    except (zipfile.BadZipFile, IndexError) as exc:
        raise FxError(f"Invalid ECB archive: {exc}") from exc

    rates = {}
    for row in csv.DictReader(io.StringIO(text)):
        value = (row.get("USD") or "").strip()
        if value and value != "N/A":
            rates[row["Date"].strip()] = float(value)
    if not rates:
        raise FxError("No USD rates found in the ECB file: format changed?")
    return rates
