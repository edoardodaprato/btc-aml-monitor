"""Build the profile of one address: its history, normalised and priced in EUR."""

from __future__ import annotations

from btc_aml.config import AppConfig
from btc_aml.model import AddressProfile, Transaction
from btc_aml.services import Services


def build_address_profile(address: str, services: Services, config: AppConfig) -> AddressProfile:
    """Download (or read from cache) the address history and convert it to the model."""
    stats = services.esplora.get_address_stats(address)["chain_stats"]
    history = services.esplora.get_address_history(address, config.exposure.max_tx_per_address)

    txs = [
        Transaction.from_esplora(raw, services.prices.eur_price(raw["status"]["block_time"]))
        for raw in history.txs
    ]
    txs.sort(key=lambda tx: (tx.block_height or 0, tx.txid))  # oldest first, deterministic

    return AddressProfile(
        address=address,
        txs=tuple(txs),
        tx_count_total=stats["tx_count"],
        total_received_sats=stats["funded_txo_sum"],
        total_sent_sats=stats["spent_txo_sum"],
        truncated=history.truncated,
    )
