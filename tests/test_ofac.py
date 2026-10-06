"""Tests for OFAC SDN parsing and storage (real entries, offline)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from btc_aml.data_sources.ofac import OfacError, load_ofac_list, parse_sdn_xml, update_ofac_list
from tests.conftest import FIXTURES

SAMPLE_XML = (FIXTURES / "ofac_sdn_sample.xml").read_bytes()
# Real SDN entries contained in the sample: an entity with six XBT addresses, one with a
# single address, and two individuals designated with the same address.
MULTI_ADDRESS_ENTITY = "YAN"
SINGLE_ADDRESS = "12aNKp2iDKuhEde2YfPdd4DFGenRUTKupL"
SHARED_ADDRESS = "1H939dom7i4WDLCKyGbXUp3fs9CSTNRzgL"


def serve(body: bytes, status: int = 200) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, content=body))


def test_parse_extracts_only_xbt_addresses() -> None:
    publish_date, record_count, addresses = parse_sdn_xml(SAMPLE_XML)

    assert publish_date == "2026-10-05"
    assert record_count == 6
    assert len(addresses) == 14  # the ETH-only entity and the airline contribute none
    assert len({a.address for a in addresses}) == 13  # one address is shared
    assert all(not a.address.startswith("0x") for a in addresses)


def test_parse_keeps_entity_and_programs() -> None:
    _, _, addresses = parse_sdn_xml(SAMPLE_XML)
    by_entity = [a for a in addresses if a.entity_name.endswith(MULTI_ADDRESS_ENTITY)]

    assert len(by_entity) == 6
    assert by_entity[0].programs  # sanctions programme codes are preserved
    assert by_entity[0].entity_uid


def test_update_saves_and_reloads_with_version(tmp_path: Path) -> None:
    target = tmp_path / "ofac" / "list.json"

    saved = update_ofac_list("https://ofac.test/SDN.XML", target, transport=serve(SAMPLE_XML))
    loaded = load_ofac_list(target)

    assert loaded == saved
    assert SINGLE_ADDRESS in loaded.addresses
    assert loaded.version.startswith("2026-10-05 / sha256:")


def test_address_shared_by_two_entities_keeps_both(tmp_path: Path) -> None:
    target = tmp_path / "list.json"
    update_ofac_list("https://ofac.test/SDN.XML", target, transport=serve(SAMPLE_XML))

    entries = load_ofac_list(target).addresses[SHARED_ADDRESS]

    assert len({entry.entity_uid for entry in entries}) == 2


def test_update_fails_when_no_xbt_entries(tmp_path: Path) -> None:
    empty = b'<?xml version="1.0"?><sdnList><publshInformation/></sdnList>'

    with pytest.raises(OfacError, match="format changed"):
        update_ofac_list("https://ofac.test/SDN.XML", tmp_path / "l.json", transport=serve(empty))


def test_update_reports_download_errors(tmp_path: Path) -> None:
    with pytest.raises(OfacError, match="Could not download"):
        update_ofac_list(
            "https://ofac.test/SDN.XML", tmp_path / "l.json", transport=serve(b"", 503)
        )


def test_load_missing_list_explains_how_to_fix(tmp_path: Path) -> None:
    with pytest.raises(OfacError, match="btc-aml update-ofac"):
        load_ofac_list(tmp_path / "missing.json")
