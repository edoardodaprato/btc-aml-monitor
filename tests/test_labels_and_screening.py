"""Tests for the labels file and for list screening."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from btc_aml.data_sources.labels import (
    Label,
    LabelError,
    import_labels,
    is_valid_btc_address,
    read_labels,
)
from btc_aml.data_sources.ofac import update_ofac_list
from btc_aml.screening import Screener
from tests.conftest import FIXTURES

HEADER = "address,category,source,date_added\n"
# Example addresses published in the BIP-173 specification. Labels attached to them in
# these tests are fictitious: never attribute a category to a real address without a source.
ADDR_A = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
ADDR_B = "bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3"
OFAC_ADDRESS = "12aNKp2iDKuhEde2YfPdd4DFGenRUTKupL"


def write_csv(path: Path, *rows: str) -> Path:
    path.write_text(HEADER + "".join(f"{row}\n" for row in rows))
    return path


@pytest.mark.parametrize(
    ("address", "valid"),
    [
        ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", True),  # P2PKH
        ("3NLtx2hjkY7z8kghphzoZNGH8PP1u11YsT", True),  # P2SH
        (ADDR_A, True),  # P2WPKH
        (ADDR_B, True),  # P2WSH
        ("0x252a8bd2319d8a555b872990601221b3a2053bce", False),  # Ethereum
        (ADDR_A.upper(), False),  # upper-case bech32 is not accepted
        ("", False),
    ],
)
def test_address_format(address: str, valid: bool) -> None:
    assert is_valid_btc_address(address) is valid


def test_missing_labels_file_means_no_labels(tmp_path: Path) -> None:
    assert read_labels(tmp_path / "labels.csv") == []


def test_template_is_a_valid_empty_file() -> None:
    template = FIXTURES.parent.parent / "data" / "labels_template.csv"
    assert read_labels(template) == []


def test_invalid_rows_are_all_reported(tmp_path: Path) -> None:
    source = write_csv(
        tmp_path / "bad.csv",
        f"{ADDR_A},casino,https://example.org/report,2026-01-01",
        "not-an-address,mixer,https://example.org/report,2026-01-01",
        f"{ADDR_B},scam,,2026-01-01",
        f"{ADDR_B},scam,https://example.org/report,01/01/2026",
    )

    with pytest.raises(LabelError) as excinfo:
        read_labels(source)
    message = str(excinfo.value)
    for expected in ("line 2", "line 3", "line 4", "line 5", "unknown category", "missing source"):
        assert expected in message


def test_import_merges_and_skips_duplicates(tmp_path: Path) -> None:
    target = tmp_path / "labels.csv"
    first = write_csv(tmp_path / "a.csv", f"{ADDR_A},exchange,https://example.org/a,2026-01-01")
    second = write_csv(
        tmp_path / "b.csv",
        f"{ADDR_A},exchange,https://example.org/a,2026-01-01",
        f"{ADDR_B},scam,https://example.org/b,2026-02-01",
    )

    assert import_labels(first, target).added == 1
    result = import_labels(second, target)

    assert (result.added, result.duplicates, result.total) == (1, 1, 2)
    assert [label.address for label in read_labels(target)] == [ADDR_A, ADDR_B]


def test_rejected_import_leaves_target_untouched(tmp_path: Path) -> None:
    target = write_csv(
        tmp_path / "labels.csv", f"{ADDR_A},exchange,https://example.org/a,2026-01-01"
    )
    before = target.read_text()
    bad = write_csv(tmp_path / "bad.csv", f"{ADDR_B},unknown,https://example.org,2026-01-01")

    with pytest.raises(LabelError):
        import_labels(bad, target)
    assert target.read_text() == before


def test_screener_combines_ofac_and_labels(tmp_path: Path) -> None:
    xml = (FIXTURES / "ofac_sdn_sample.xml").read_bytes()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=xml))
    ofac = update_ofac_list("https://ofac.test/SDN.XML", tmp_path / "o.json", transport=transport)
    labels = [Label(ADDR_B, "mixer", "https://example.org/report", "2026-01-01")]
    screener = Screener(ofac, labels)

    ofac_hits = screener.screen(OFAC_ADDRESS)
    assert ofac_hits[0].list_name == "OFAC SDN"
    assert "SDN uid" in ofac_hits[0].detail
    assert screener.is_sanctioned(OFAC_ADDRESS)

    label_hits = screener.screen(ADDR_B)
    assert [(h.list_name, h.category) for h in label_hits] == [("labels", "mixer")]
    assert not screener.is_sanctioned(ADDR_B)

    assert screener.screen(ADDR_A) == []


def test_screener_without_ofac_list() -> None:
    screener = Screener(None, [])

    assert screener.ofac_version == "not loaded"
    assert screener.screen(OFAC_ADDRESS) == []
