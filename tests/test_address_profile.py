"""Tests for the address profile builder (real fixtures, offline)."""

from __future__ import annotations

from btc_aml.address_profile import build_address_profile
from btc_aml.config import AppConfig
from btc_aml.services import Services
from tests.conftest import FIXTURE_ADDRESS, FIXTURE_ADDRESS_TX_COUNT, FakeEsplora


def test_profile_from_real_fixture(app_config: AppConfig, fake_esplora: FakeEsplora) -> None:
    with Services.from_config(app_config, transport=fake_esplora.transport()) as services:
        prof = build_address_profile(FIXTURE_ADDRESS, services, app_config)

    assert len(prof.txs) == FIXTURE_ADDRESS_TX_COUNT
    assert not prof.truncated
    assert [tx.block_height for tx in prof.txs] == sorted(tx.block_height for tx in prof.txs)
    # The reconstructed balance after the last transaction equals the API balance.
    assert prof.balance_timeline()[-1][1] == prof.balance_sats
