"""Extraction des couples type@location et de leur disponibilité depuis la réponse API."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Offer:
    """Un type de serveur dans une location, avec sa disponibilité et son prix mensuel HT."""

    server_type: str
    location: str
    available: bool
    price_net: str | None = None
    cores: int | None = None
    memory: float | None = None
    architecture: str = ""

    @property
    def key(self) -> str:
        return offer_key(self.server_type, self.location)


def offer_key(server_type: str, location: str) -> str:
    return f"{server_type}@{location}"


def iter_offers(server_types: Iterable[dict[str, Any]]) -> Iterator[Offer]:
    """Tous les couples non dépréciés (deprecation non nulle = on ignore le couple)."""
    for st in server_types:
        name = str(st.get("name") or "").lower()
        if not name:
            continue
        prices = {
            str(p.get("location") or "").lower(): (p.get("price_monthly") or {}).get("net")
            for p in st.get("prices") or []
            if isinstance(p, dict)
        }
        cores = st.get("cores")
        memory = st.get("memory")
        for loc in st.get("locations") or []:
            if not isinstance(loc, dict) or loc.get("deprecation") is not None:
                continue
            loc_name = str(loc.get("name") or "").lower()
            if not loc_name:
                continue
            price = prices.get(loc_name)
            yield Offer(
                server_type=name,
                location=loc_name,
                available=loc.get("available") is True,
                price_net=str(price) if price is not None else None,
                cores=cores if isinstance(cores, int) else None,
                memory=float(memory) if isinstance(memory, (int, float)) else None,
                architecture=str(st.get("architecture") or ""),
            )


def extract(
    server_types: Iterable[dict[str, Any]], types: Sequence[str], locations: Sequence[str] = ()
) -> dict[str, Offer]:
    """Couples surveillés : types demandés, locations demandées (vide = toutes)."""
    wanted_types = set(types)
    wanted_locations = set(locations)
    return {
        offer.key: offer
        for offer in iter_offers(server_types)
        if offer.server_type in wanted_types and (not wanted_locations or offer.location in wanted_locations)
    }


def missing_types(server_types: Iterable[dict[str, Any]], types: Sequence[str]) -> list[str]:
    """Types configurés absents de l'API ou dépréciés partout (faute de frappe, ex. cx42 retiré)."""
    known = {offer.server_type for offer in iter_offers(server_types)}
    return [t for t in types if t not in known]


def format_price(net: str | None) -> str:
    """'9.4900' -> '9,49 € HT/mois' ; '' si absent ou illisible."""
    if net is None:
        return ""
    try:
        value = Decimal(net).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return ""
    return f"{value:.2f}".replace(".", ",") + " € HT/mois"


def format_memory(memory: float | None) -> str:
    if memory is None:
        return ""
    text = f"{memory:g}".replace(".", ",")
    return f"{text} Go"


def describe(offer: Offer) -> str:
    """'CX43 à fsn1 (8 vCPU, 16 Go, x86) : 9,49 € HT/mois'."""
    specs = []
    if offer.cores is not None:
        specs.append(f"{offer.cores} vCPU")
    if offer.memory is not None:
        specs.append(format_memory(offer.memory))
    if offer.architecture:
        specs.append(offer.architecture)
    text = f"{offer.server_type.upper()} à {offer.location}"
    if specs:
        text += f" ({', '.join(specs)})"
    price = format_price(offer.price_net)
    if price:
        text += f" : {price}"
    return text
