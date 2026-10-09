"""Block-scan mode: look for red flags in every transaction of a range of blocks.

Address mode starts from addresses a compliance officer already cares about. Block
scan starts from the blockchain itself: it reads every transaction of a few blocks and
flags those that, on their own, show a red flag. It answers "what in these blocks
deserves a closer look?", not "how risky is this customer?": findings are attached to
transactions, not scored per address. Addresses linked to sanctioned or labelled
addresses are listed so they can be analysed in full with address mode.

Only the checks that make sense on a single transaction run here. Rules that need an
address history (structuring, velocity, dormancy, peel chains...) are address-mode only.
Thresholds, severities and on/off switches come from ``rules.yaml``, so both modes use
the same calibration.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from btc_aml.config import AppConfig
from btc_aml.data_sources.price import PriceQuote
from btc_aml.graph.change import detect_change
from btc_aml.graph.clustering import cluster_transactions
from btc_aml.heuristics import detect_coinjoin
from btc_aml.model import SATS_PER_BTC, Transaction
from btc_aml.rules.base import describe_hits, exceeds_threshold, fmt_amount
from btc_aml.rules.registry import ALL_RULES
from btc_aml.screening import Screener

BLOCK_SCAN_RULES = (
    "R01_OFAC_DIRECT",
    "R03_HIGH_RISK_CATEGORY",
    "R04_COINJOIN",
    "R09_FAN_OUT",
    "R14_LARGE_TRANSACTION",
    "R16_CONSOLIDATION",
    "R19_CO_SPENDING_FLAGGED",
    "R21_ANOMALOUS_FEE",
)
MAX_LISTED_ADDRESSES = 10  # longer address lists are shortened in the report
# Above this size a common-input cluster most likely belongs to a custodial service (an
# exchange sweeping customer deposits): the flagged address is then probably one
# customer's deposit address, and the other members are not the sanctioned party.
LARGE_CLUSTER = 50
REVIEW_RULES = frozenset({"R01_OFAC_DIRECT", "R03_HIGH_RISK_CATEGORY", "R19_CO_SPENDING_FLAGGED"})


@dataclass(frozen=True)
class BlockFinding:
    """A red flag raised by one transaction (or one group of transactions) in a block."""

    rule_id: str
    rule_name: str
    severity: str
    regulatory_reference: str
    block_height: int
    block_time: int
    txids: tuple[str, ...]
    addresses: tuple[str, ...]  # addresses the finding is about
    amount_sats: int
    amount_eur: float | None
    explanation: str


@dataclass(frozen=True)
class BlockInfo:
    height: int
    block_hash: str
    timestamp: int
    tx_count: int
    median_fee_rate: float | None  # sat/vB, from mempool.space; None if unavailable
    price: PriceQuote | None  # BTC/EUR on the block day


@dataclass
class BlockReport:
    block: BlockInfo
    txs: list[Transaction]
    findings: list[BlockFinding]

    @property
    def addresses_for_review(self) -> set[str]:
        """Addresses listed or linked to a listed address: candidates for address mode.

        Members of large clusters are left out (see ``large_cluster_addresses``).
        """
        return {
            a
            for f in self.findings
            if f.rule_id in REVIEW_RULES and not _is_large_cluster(f)
            for a in f.addresses
        }

    @property
    def large_cluster_addresses(self) -> set[str]:
        """Members of large clusters linked to a listed address (likely a custodial service)."""
        return {a for f in self.findings if _is_large_cluster(f) for a in f.addresses} - (
            self.addresses_for_review
        )


def _is_large_cluster(finding: BlockFinding) -> bool:
    return finding.rule_id == "R19_CO_SPENDING_FLAGGED" and len(finding.addresses) > LARGE_CLUSTER


class BlockScanner:
    """Applies the single-transaction checks to the transactions of one block."""

    def __init__(self, config: AppConfig, screener: Screener) -> None:
        self._config = config
        self._screener = screener
        self._classes = {cls.rule_id: cls for cls in ALL_RULES}
        self._enabled = {
            rule_id
            for rule_id in BLOCK_SCAN_RULES
            if rule_id in config.rules and config.rules[rule_id].enabled
        }

    @property
    def enabled_rules(self) -> list[str]:
        return [rule_id for rule_id in BLOCK_SCAN_RULES if rule_id in self._enabled]

    def scan(self, block: BlockInfo, raw_txs: Iterable[dict[str, Any]]) -> BlockReport:
        eur = block.price.eur if block.price else None
        eur_date = block.price.as_of if block.price else None
        eur_source = block.price.source if block.price else None
        txs = [Transaction.from_esplora(raw, eur, eur_date, eur_source) for raw in raw_txs]
        findings: list[BlockFinding] = []
        for tx in txs:
            if tx.is_coinbase:
                continue
            findings.extend(self._screening(block, tx))
            findings.extend(self._structure(block, tx))
        findings.extend(self._co_spending(block, txs))
        return BlockReport(block, txs, findings)

    # --- checks ---------------------------------------------------------------------

    def _screening(self, block: BlockInfo, tx: Transaction) -> list[BlockFinding]:
        """R01/R03: a sanctioned or labelled address sends or receives in this transaction."""
        findings = []
        high_risk = set(self._params("R03_HIGH_RISK_CATEGORY").get("categories", ()))
        for address in sorted(tx.input_addresses | tx.output_addresses):
            hits = self._screener.screen(address)
            sent, received = tx.sent_by(address), tx.received_by(address)
            role = "sends" if sent else "receives"
            amount = sent or received
            for rule_id, categories in (
                ("R01_OFAC_DIRECT", {"sanctioned"}),
                ("R03_HIGH_RISK_CATEGORY", high_risk),
            ):
                matched = [h for h in hits if h.category in categories]
                if rule_id in self._enabled and matched:
                    findings.append(
                        self._finding(
                            rule_id,
                            block,
                            [tx],
                            [address],
                            amount,
                            tx.to_eur(amount),
                            f"{address} ({describe_hits(matched)}) {role} "
                            f"{fmt_amount(amount, tx.to_eur(amount))} in this transaction.",
                        )
                    )
        return findings

    def _structure(self, block: BlockInfo, tx: Transaction) -> list[BlockFinding]:
        """R04, R09, R14, R16, R21: red flags visible in the shape of the transaction."""
        findings = []
        inputs = sorted(tx.input_addresses)
        coinjoin = detect_coinjoin(tx, self._config.coinjoin)
        total = tx.total_output_sats

        if coinjoin and "R04_COINJOIN" in self._enabled:
            findings.append(
                self._finding(
                    "R04_COINJOIN",
                    block,
                    [tx],
                    inputs,
                    total,
                    tx.to_eur(total),
                    f"{coinjoin.kind} CoinJoin: {len(tx.inputs)} inputs, "
                    f"{coinjoin.equal_outputs} equal outputs of "
                    f"{coinjoin.denomination_sats / SATS_PER_BTC:.8f} BTC; total "
                    f"{fmt_amount(total, tx.to_eur(total))}.",
                )
            )
        if coinjoin:
            return findings  # the other structural checks do not apply to CoinJoins

        params = self._params("R09_FAN_OUT")
        recipients = tx.output_addresses - tx.input_addresses
        if "R09_FAN_OUT" in self._enabled and len(recipients) >= params["min_recipients"]:
            findings.append(
                self._finding(
                    "R09_FAN_OUT",
                    block,
                    [tx],
                    inputs,
                    total,
                    tx.to_eur(total),
                    f"One transaction pays {len(recipients)} distinct addresses "
                    f"({fmt_amount(total, tx.to_eur(total))}). Typical of exchange or pool "
                    f"batch payouts, but also of distribution to money mules.",
                )
            )

        params = self._params("R14_LARGE_TRANSACTION")
        change = detect_change(tx)
        transferred = total - (change.output.value_sats if change else 0)
        if "R14_LARGE_TRANSACTION" in self._enabled:
            large, basis = exceeds_threshold(
                transferred,
                tx.to_eur(transferred),
                params["threshold_eur"],
                params["threshold_btc"],
            )
            if large:
                change_text = f" (excluding change, {change.heuristic})" if change else ""
                findings.append(
                    self._finding(
                        "R14_LARGE_TRANSACTION",
                        block,
                        [tx],
                        inputs,
                        transferred,
                        tx.to_eur(transferred),
                        f"Transfers {fmt_amount(transferred, tx.to_eur(transferred))}"
                        f"{change_text}; {basis}.",
                    )
                )

        params = self._params("R16_CONSOLIDATION")
        if "R16_CONSOLIDATION" in self._enabled:
            max_input = round(params["max_input_btc"] * SATS_PER_BTC)
            small = sum(1 for i in tx.inputs if 0 < i.value_sats <= max_input)
            if small >= params["min_inputs"]:
                findings.append(
                    self._finding(
                        "R16_CONSOLIDATION",
                        block,
                        [tx],
                        inputs,
                        total,
                        tx.to_eur(total),
                        f"Merges {small} inputs of at most {params['max_input_btc']} BTC "
                        f"from {len(inputs)} address(es) into "
                        f"{fmt_amount(total, tx.to_eur(total))}.",
                    )
                )

        params = self._params("R21_ANOMALOUS_FEE")
        median = block.median_fee_rate
        if (
            "R21_ANOMALOUS_FEE" in self._enabled
            and median
            and tx.fee_sats >= params["min_fee_sats"]
            and tx.fee_rate >= params["min_fee_multiple"] * median
        ):
            findings.append(
                self._finding(
                    "R21_ANOMALOUS_FEE",
                    block,
                    [tx],
                    inputs,
                    tx.fee_sats,
                    tx.to_eur(tx.fee_sats),
                    f"Fee rate {tx.fee_rate:.1f} sat/vB is {tx.fee_rate / median:.0f}x the "
                    f"block median ({median:.1f}); fee "
                    f"{fmt_amount(tx.fee_sats, tx.to_eur(tx.fee_sats))}.",
                )
            )
        return findings

    def _co_spending(self, block: BlockInfo, txs: list[Transaction]) -> list[BlockFinding]:
        """R19: addresses clustered (common input / change) with a flagged address.

        Clustering runs across the whole block, so two transactions sharing an input
        address or a change output are linked even if they look unrelated.
        """
        if "R19_CO_SPENDING_FLAGGED" not in self._enabled:
            return []
        categories = set(self._params("R19_CO_SPENDING_FLAGGED")["categories"])
        clusters = cluster_transactions(txs, self._config.coinjoin)
        findings = []
        for group in clusters.groups():
            flagged = {
                a: hits
                for a in sorted(group)
                if (hits := [h for h in self._screener.screen(a) if h.category in categories])
            }
            linked = sorted(group - flagged.keys())
            if not flagged or not linked:
                continue
            evidence = [tx for tx in txs if (tx.input_addresses | tx.output_addresses) & group]
            flagged_text = "; ".join(f"{a} ({describe_hits(h)})" for a, h in flagged.items())
            moved = sum(tx.sent_by(a) for tx in evidence for a in linked)
            eur = block.price.eur * moved / SATS_PER_BTC if block.price else None
            caveat = (
                f" Cluster larger than {LARGE_CLUSTER} addresses: typical of a custodial "
                f"service sweeping customer deposits, in which case the flagged address is a "
                f"customer deposit and the service is the counterparty to contact."
                if len(linked) > LARGE_CLUSTER
                else ""
            )
            findings.append(
                self._finding(
                    "R19_CO_SPENDING_FLAGGED",
                    block,
                    evidence,
                    linked,
                    moved,
                    eur,
                    f"{len(linked)} address(es) are clustered with {flagged_text} by the "
                    f"common-input-ownership and change heuristics in this block: probably the "
                    f"same wallet. Value they spent: {fmt_amount(moved, eur)}.{caveat}",
                )
            )
        return findings

    # --- helpers --------------------------------------------------------------------

    def _params(self, rule_id: str) -> dict[str, Any]:
        rule = self._config.rules.get(rule_id)
        return rule.params if rule else {}

    def _finding(
        self,
        rule_id: str,
        block: BlockInfo,
        txs: list[Transaction],
        addresses: Iterable[str],
        amount_sats: int,
        amount_eur: float | None,
        explanation: str,
    ) -> BlockFinding:
        cls = self._classes[rule_id]
        return BlockFinding(
            rule_id=rule_id,
            rule_name=cls.name,
            severity=self._config.rules[rule_id].severity,
            regulatory_reference=cls.regulatory_reference,
            block_height=block.height,
            block_time=block.timestamp,
            txids=tuple(tx.txid for tx in txs),
            addresses=tuple(addresses),
            amount_sats=amount_sats,
            amount_eur=amount_eur,
            explanation=explanation,
        )
