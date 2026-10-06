"""List screening: is an address on the OFAC SDN list or in the user's labels?

This is the building block of the sanctions and high-risk-category rules: those rules
decide *how much* an exposure matters, this module only answers *whether* an address
is listed and on which basis.
"""

from __future__ import annotations

from dataclasses import dataclass

from btc_aml.data_sources.labels import Label
from btc_aml.data_sources.ofac import OfacList

OFAC_LIST_NAME = "OFAC SDN"
LABELS_LIST_NAME = "labels"


@dataclass(frozen=True)
class ScreeningHit:
    address: str
    list_name: str  # "OFAC SDN" or "labels"
    category: str  # "sanctioned" for OFAC, the label category otherwise
    detail: str  # entity and programmes for OFAC, source for labels


class Screener:
    """In-memory lookup over the OFAC list and the labels file."""

    def __init__(self, ofac: OfacList | None, labels: list[Label]) -> None:
        self._ofac = ofac
        self._labels: dict[str, list[Label]] = {}
        for label in labels:
            self._labels.setdefault(label.address, []).append(label)

    @property
    def ofac_version(self) -> str:
        return self._ofac.version if self._ofac else "not loaded"

    def screen(self, address: str) -> list[ScreeningHit]:
        hits = []
        ofac_entries = self._ofac.addresses.get(address, ()) if self._ofac else ()
        for entry in ofac_entries:
            programs = ", ".join(entry.programs) or "n/a"
            detail = f"{entry.entity_name} (SDN uid {entry.entity_uid}; programs: {programs})"
            hits.append(
                ScreeningHit(
                    address=address,
                    list_name=OFAC_LIST_NAME,
                    category="sanctioned",
                    detail=detail,
                )
            )
        for label in self._labels.get(address, []):
            hits.append(
                ScreeningHit(
                    address=address,
                    list_name=LABELS_LIST_NAME,
                    category=label.category,
                    detail=f"source: {label.source} (added {label.date_added})",
                )
            )
        return hits

    def is_sanctioned(self, address: str) -> bool:
        return any(hit.category == "sanctioned" for hit in self.screen(address))
