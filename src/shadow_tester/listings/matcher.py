"""DVF ↔ listing matcher — retroactively link past listings to DVF sales.

Given a listing (price, surface, type, commune, first_seen date) and a pool
of DVF mutations, the matcher computes a weighted similarity score to find
the most likely corresponding sale.

This lets us backfill DVF transactions with property condition information
from listings the user has captured, and compute time-on-market + negotiation
margin statistics.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta

from shadow_tester.comps.scoring import haversine_km
from shadow_tester.listings.models import Listing
from shadow_tester.storage import connect

logger = logging.getLogger(__name__)

# ── Match scoring weights ────────────────────────────────────────────────

_W_PRICE = 0.35
_W_SURFACE = 0.25
_W_ROOMS = 0.15
_W_TEMPORAL = 0.15
_W_DISTANCE = 0.10

# ── Thresholds ───────────────────────────────────────────────────────────

AUTO_MATCH_THRESHOLD = 0.80
SUGGEST_THRESHOLD = 0.60

# Hard filters before scoring.
_SURFACE_TOL = 0.10       # ±10% surface match
_MAX_MONTHS_GAP = 12      # listing must precede mutation by ≤ 12 months
_MAX_GEO_KM = 0.5         # max distance between listing and DVF coords


@dataclass
class MatchCandidate:
    """A potential DVF mutation that could correspond to a listing."""

    id_mutation: str
    date_mutation: str
    valeur_fonciere: float
    surface: float
    rooms: int | None
    type_local: str
    lat: float | None
    lon: float | None

    # Computed
    score: float = 0.0
    price_delta_pct: float | None = None    # (dvf - listing) / listing
    days_to_sale: int | None = None          # listing.first_seen → mutation.date


@dataclass
class MatchResult:
    """Result of matching one listing against DVF."""

    listing_id: int
    candidates: list[MatchCandidate]
    best: MatchCandidate | None = None
    auto_matched: bool = False


# ── Candidate SQL ────────────────────────────────────────────────────────

_CANDIDATE_SQL = """
SELECT
    id_mutation, date_mutation, valeur_fonciere,
    surface_reelle_bati AS surface,
    nombre_pieces_principales AS rooms,
    type_local,
    longitude AS lon,
    latitude AS lat
FROM dvf_transactions
WHERE code_commune = :commune
  AND type_local = :type_local
  AND valeur_fonciere IS NOT NULL
  AND surface_reelle_bati IS NOT NULL
  AND surface_reelle_bati BETWEEN :smin AND :smax
  AND date_mutation >= :date_min
  AND date_mutation <= :date_max
"""


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _price_score(listing_price: float, dvf_price: float) -> float:
    """Gaussian-ish score centered at -8% (median French negotiation margin)."""
    if listing_price <= 0:
        return 0.0
    delta = (dvf_price - listing_price) / listing_price
    # Center at -0.08 (i.e. DVF price typically 8% below asking).
    # Sigma ~0.10 → gentle falloff.
    return math.exp(-0.5 * ((delta + 0.08) / 0.10) ** 2)


def _surface_score(listing_surface: float, dvf_surface: float) -> float:
    if listing_surface <= 0:
        return 0.0
    err = abs(dvf_surface - listing_surface) / listing_surface
    return max(0.0, 1.0 - err / _SURFACE_TOL)


def _rooms_score(listing_rooms: int | None, dvf_rooms: int | None) -> float:
    if listing_rooms is None or dvf_rooms is None:
        return 0.5  # neutral
    diff = abs(dvf_rooms - listing_rooms)
    if diff == 0:
        return 1.0
    if diff == 1:
        return 0.5
    return 0.0


def _temporal_score(listing_first_seen: date, mutation_date: date) -> float:
    """Prefer mutations that happen 1-4 months after the listing appeared."""
    days = (mutation_date - listing_first_seen).days
    if days < 0:
        return 0.0  # mutation before listing — impossible match
    months = days / 30.0
    if months <= 1:
        return 0.8  # very fast sale
    if months <= 4:
        return 1.0  # sweet spot
    if months <= 8:
        return 0.6
    return 0.3  # stale but possible


def _geo_score(
    listing_lat: float | None,
    listing_lon: float | None,
    dvf_lat: float | None,
    dvf_lon: float | None,
) -> float:
    if listing_lat is None or listing_lon is None:
        return 0.5  # neutral — no data
    if dvf_lat is None or dvf_lon is None:
        return 0.5  # neutral
    d = haversine_km(listing_lat, listing_lon, dvf_lat, dvf_lon)
    if d <= 0.05:  # ~50m
        return 1.0
    if d <= _MAX_GEO_KM:
        return max(0.0, 1.0 - d / _MAX_GEO_KM)
    return 0.0


def _score_candidate(
    listing: Listing,
    cand: MatchCandidate,
    listing_date: date,
    mutation_date: date,
) -> float:
    ps = _price_score(listing.price_asked or 0, cand.valeur_fonciere)
    ss = _surface_score(listing.surface or 0, cand.surface)
    rs = _rooms_score(listing.rooms, cand.rooms)
    ts = _temporal_score(listing_date, mutation_date)
    gs = _geo_score(listing.lat, listing.lon, cand.lat, cand.lon)

    return (
        _W_PRICE * ps
        + _W_SURFACE * ss
        + _W_ROOMS * rs
        + _W_TEMPORAL * ts
        + _W_DISTANCE * gs
    )


def match_listing(listing: Listing) -> MatchResult:
    """Find the best DVF mutation matching this listing.

    Hard filters: same commune + type_local, surface within ±10%,
    mutation date between listing.first_seen and first_seen + 12 months.
    """
    result = MatchResult(listing_id=listing.id or 0, candidates=[])

    if not listing.commune or not listing.type_local:
        logger.info("Listing #%s missing commune or type — skipping match", listing.id)
        return result

    listing_date = _parse_date(listing.first_seen)
    if listing_date is None:
        logger.info("Listing #%s has no first_seen date — skipping match", listing.id)
        return result

    surface = listing.surface or 0
    if surface <= 0:
        logger.info("Listing #%s has no surface — skipping match", listing.id)
        return result

    date_min = listing_date.isoformat()
    date_max = (listing_date + timedelta(days=_MAX_MONTHS_GAP * 30)).isoformat()

    params = {
        "commune": listing.commune,
        "type_local": listing.type_local,
        "smin": surface * (1.0 - _SURFACE_TOL),
        "smax": surface * (1.0 + _SURFACE_TOL),
        "date_min": date_min,
        "date_max": date_max,
    }

    with connect() as conn:
        rows = conn.execute(_CANDIDATE_SQL, params).fetchall()

    seen_ids: set[str] = set()
    for row in rows:
        mid = row["id_mutation"]
        if mid in seen_ids:
            continue
        seen_ids.add(mid)

        mutation_date = _parse_date(row["date_mutation"])
        if mutation_date is None:
            continue

        cand = MatchCandidate(
            id_mutation=mid,
            date_mutation=row["date_mutation"],
            valeur_fonciere=float(row["valeur_fonciere"]),
            surface=float(row["surface"]),
            rooms=int(row["rooms"]) if row["rooms"] is not None else None,
            type_local=row["type_local"],
            lat=float(row["lat"]) if row["lat"] is not None else None,
            lon=float(row["lon"]) if row["lon"] is not None else None,
        )

        cand.score = round(
            _score_candidate(listing, cand, listing_date, mutation_date),
            4,
        )

        if listing.price_asked and listing.price_asked > 0:
            cand.price_delta_pct = round(
                (cand.valeur_fonciere - listing.price_asked) / listing.price_asked * 100,
                1,
            )

        cand.days_to_sale = (mutation_date - listing_date).days

        result.candidates.append(cand)

    # Sort best first.
    result.candidates.sort(key=lambda c: -c.score)

    if result.candidates:
        best = result.candidates[0]
        if best.score >= SUGGEST_THRESHOLD:
            result.best = best
        if best.score >= AUTO_MATCH_THRESHOLD:
            result.auto_matched = True

    return result


def match_all_unmatched(
    commune: str | None = None,
) -> list[MatchResult]:
    """Run the matcher on all unmatched listings and return results."""
    from shadow_tester.listings.repo import list_listings

    listings = list_listings(
        commune=commune,
        unmatched_only=True,
        limit=500,
    )
    results = []
    for listing in listings:
        mr = match_listing(listing)
        if mr.best is not None:
            results.append(mr)
    return results
