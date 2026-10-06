"""OFAC SDN list: download, extract Bitcoin addresses, store with version metadata.

The U.S. Treasury publishes the Specially Designated Nationals (SDN) list as XML.
Bitcoin addresses appear as identifiers of type "Digital Currency Address - XBT"
attached to a sanctioned person or entity. We keep only those, together with the
entity name and sanctions programmes, plus the publication date and a SHA-256 of
the downloaded file: these form the "OFAC list version" written to every audit log.
"""

from __future__ import annotations

import hashlib
import io
import json
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

XBT_ID_TYPE = "Digital Currency Address - XBT"
DOWNLOAD_TIMEOUT_SECONDS = 120


class OfacError(RuntimeError):
    """The SDN list could not be downloaded, parsed or loaded."""


@dataclass(frozen=True)
class SanctionedAddress:
    address: str
    entity_uid: str
    entity_name: str
    programs: tuple[str, ...]


@dataclass(frozen=True)
class OfacList:
    publish_date: str  # ISO date printed by OFAC in the file
    downloaded_at: str
    source_url: str
    sha256: str
    record_count: int
    # One address can be designated under several entities: keep every attribution.
    addresses: dict[str, tuple[SanctionedAddress, ...]]

    @property
    def version(self) -> str:
        """Short identifier for audit logs, e.g. '2026-10-05 / sha256:3f1a9c0d2b7e'."""
        return f"{self.publish_date} / sha256:{self.sha256[:12]}"


def update_ofac_list(
    url: str, target: Path, transport: httpx.BaseTransport | None = None
) -> OfacList:
    """Download the SDN XML, extract XBT addresses and save them as JSON at ``target``."""
    xml_bytes = _download(url, transport)
    publish_date, record_count, addresses = parse_sdn_xml(xml_bytes)
    if not addresses:
        raise OfacError("No 'Digital Currency Address - XBT' entries found: format changed?")
    ofac_list = OfacList(
        publish_date=publish_date,
        downloaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
        source_url=url,
        sha256=hashlib.sha256(xml_bytes).hexdigest(),
        record_count=record_count,
        addresses=_group_by_address(addresses),
    )
    _save(ofac_list, target)
    return ofac_list


def load_ofac_list(path: Path) -> OfacList:
    """Load the list saved by ``update_ofac_list``."""
    if not path.is_file():
        raise OfacError(f"OFAC list not found at {path}. Run: btc-aml update-ofac")
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = [
        SanctionedAddress(**{**item, "programs": tuple(item["programs"])})
        for item in raw.pop("addresses")
    ]
    return OfacList(**raw, addresses=_group_by_address(entries))


def parse_sdn_xml(xml_bytes: bytes) -> tuple[str, int, list[SanctionedAddress]]:
    """Return (publish date, record count, XBT addresses) from an SDN XML document."""
    publish_date, record_count = "unknown", 0
    addresses: list[SanctionedAddress] = []
    try:
        for _, element in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
            tag = _local(element.tag)
            if tag == "Publish_Date":
                publish_date = _iso_date(element.text or "")
            elif tag == "Record_Count":
                record_count = int(element.text or 0)
            elif tag == "sdnEntry":
                addresses.extend(_xbt_addresses(element))
                element.clear()  # keep memory flat on the 30 MB file
    except ET.ParseError as exc:
        raise OfacError(f"Invalid SDN XML: {exc}") from exc
    return publish_date, record_count, addresses


def _group_by_address(
    entries: list[SanctionedAddress],
) -> dict[str, tuple[SanctionedAddress, ...]]:
    """Group by address, dropping exact duplicates (OFAC sometimes repeats an identifier)."""
    grouped: dict[str, list[SanctionedAddress]] = {}
    for entry in entries:
        bucket = grouped.setdefault(entry.address, [])
        if entry not in bucket:
            bucket.append(entry)
    return {address: tuple(bucket) for address, bucket in grouped.items()}


def _xbt_addresses(entry: ET.Element) -> list[SanctionedAddress]:
    fields = {_local(child.tag): child for child in entry}
    name = " ".join(
        part for part in (_text(fields.get("firstName")), _text(fields.get("lastName"))) if part
    )
    programs = tuple(_text(p) for p in fields["programList"]) if "programList" in fields else ()
    result = []
    for identifier in fields.get("idList", []):
        id_fields = {_local(child.tag): _text(child) for child in identifier}
        if id_fields.get("idType") == XBT_ID_TYPE:
            result.append(
                SanctionedAddress(
                    address=id_fields["idNumber"],
                    entity_uid=_text(fields.get("uid")),
                    entity_name=name,
                    programs=programs,
                )
            )
    return result


def _download(url: str, transport: httpx.BaseTransport | None) -> bytes:
    try:
        with httpx.Client(
            transport=transport, timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.content
    except httpx.HTTPError as exc:
        raise OfacError(f"Could not download the SDN list from {url}: {exc}") from exc


def _save(ofac_list: OfacList, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    document = asdict(ofac_list)
    document["addresses"] = [
        asdict(entry)
        for address in sorted(ofac_list.addresses)
        for entry in ofac_list.addresses[address]
    ]
    target.write_text(json.dumps(document, indent=2), encoding="utf-8")


def _local(tag: str) -> str:
    """Strip the XML namespace: '{https://...}sdnEntry' -> 'sdnEntry'."""
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


def _iso_date(us_date: str) -> str:
    """OFAC prints MM/DD/YYYY; convert to YYYY-MM-DD."""
    try:
        return datetime.strptime(us_date.strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return us_date.strip() or "unknown"
