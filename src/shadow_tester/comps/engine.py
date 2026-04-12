"""High-level comparable-properties engine.

Builds a :class:`Target` from user inputs, fetches candidate DVF rows from
SQLite with hard filters (commune / type / surface window / age), ranks them
with :func:`score_comp`, and returns a :class:`CompResult` with aggregate
price fourchette and a verdict vs the user's budget.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from shadow_tester.comps.models import Comp, CompResult, Target
from shadow_tester.comps.scoring import score_comp
from shadow_tester.listings.repo import find_listings_for_mutations
from shadow_tester.notes.repo import find_notes_for_mutations
from shadow_tester.storage import connect

logger = logging.getLogger(__name__)


_CANDIDATE_SQL = """
SELECT
    id_mutation, date_mutation, year, type_local,
    surface_reelle_bati AS surface,
    nombre_pieces_principales AS rooms,
    valeur_fonciere, prix_m2,
    COALESCE(
        NULLIF(
            TRIM(
                COALESCE(adresse_numero, '') || ' ' ||
                COALESCE(adresse_nom_voie, '')
            ),
            ''
        ),
        'adresse inconnue'
    ) AS adresse,
    adresse_nom_voie,
    longitude AS lon,
    latitude AS lat
FROM dvf_transactions
WHERE code_commune = :commune
  AND type_local = :type_local
  AND surface_reelle_bati IS NOT NULL
  AND surface_reelle_bati BETWEEN :smin AND :smax
  AND valeur_fonciere IS NOT NULL
  AND prix_m2 IS NOT NULL
  AND year IS NOT NULL
  AND year >= :min_year
"""


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = k - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def _confidence(n: int) -> str:
    if n >= 10:
        return "high"
    if n >= 5:
        return "medium"
    return "low"


def _fetch_candidates(target: Target, min_year: int) -> list[Comp]:
    params = {
        "commune": target.commune,
        "type_local": target.type_local,
        "smin": target.surface_min,
        "smax": target.surface_max,
        "min_year": min_year,
    }
    with connect() as conn:
        rows = conn.execute(_CANDIDATE_SQL, params).fetchall()

    # Optional street-keyword hard filter (substring match on adresse_nom_voie).
    keyword = (target.street_keyword or "").strip().lower()

    candidates: list[Comp] = []
    for row in rows:
        if keyword:
            voie = (row["adresse_nom_voie"] or "").lower()
            if keyword not in voie:
                continue
        candidates.append(
            Comp(
                id_mutation=row["id_mutation"],
                date_mutation=row["date_mutation"],
                year=int(row["year"]),
                type_local=row["type_local"],
                surface=float(row["surface"]),
                rooms=int(row["rooms"]) if row["rooms"] is not None else None,
                valeur_fonciere=float(row["valeur_fonciere"]),
                prix_m2=float(row["prix_m2"]) if row["prix_m2"] is not None else None,
                adresse=row["adresse"],
                lat=float(row["lat"]) if row["lat"] is not None else None,
                lon=float(row["lon"]) if row["lon"] is not None else None,
            )
        )
    return candidates


def _latest_year_in_db(commune: str) -> int | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT MAX(year) FROM dvf_transactions WHERE code_commune = ?",
            (commune,),
        ).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _aggregate(target: Target, ranked: Iterable[Comp]) -> tuple[float | None, float | None, float | None]:
    prix_m2_values = sorted(c.prix_m2 for c in ranked if c.prix_m2 is not None)
    if not prix_m2_values:
        return None, None, None
    return (
        _percentile(prix_m2_values, 0.25),
        _percentile(prix_m2_values, 0.5),
        _percentile(prix_m2_values, 0.75),
    )


def _verdict(target: Target, suggested_low: float, suggested_high: float) -> str:
    if target.budget is None:
        return ""
    if target.budget < suggested_low:
        return "Budget en-dessous de la fourchette médiane — marge possible ou bien sous-évalué."
    if target.budget > suggested_high:
        return "Budget au-dessus de la fourchette — risque de payer trop cher vs marché."
    return "Budget dans la fourchette médiane du marché."


def find_comparables(target: Target) -> CompResult:
    """Return the top-``target.limit`` comparable transactions for ``target``."""
    latest_year = _latest_year_in_db(target.commune)
    if latest_year is None:
        logger.info("No DVF data at all for commune %s", target.commune)
        return CompResult(target=target)
    min_year = latest_year - target.max_years_old + 1

    candidates = _fetch_candidates(target, min_year=min_year)
    logger.info(
        "Found %d candidate DVF rows for target (commune=%s, type=%s, surface~%s, window=%.0f-%.0f m²)",
        len(candidates),
        target.commune,
        target.type_local,
        target.surface,
        target.surface_min,
        target.surface_max,
    )

    for comp in candidates:
        score_comp(comp, target, latest_year=latest_year)

    # Rank by total_score desc, then by distance asc (None last).
    candidates.sort(
        key=lambda c: (
            -c.total_score,
            float("inf") if c.distance_km is None else c.distance_km,
        )
    )
    top = candidates[: target.limit]

    # Enrich with condition from user notes (ground truth, highest priority).
    notes_map = find_notes_for_mutations(c.id_mutation for c in top)
    for comp in top:
        note = notes_map.get(comp.id_mutation)
        if note is not None:
            comp.condition = note.condition
            comp.condition_source = note.source

    # Second pass: fill gaps from matched listings (lower priority than notes).
    missing = [c.id_mutation for c in top if c.condition is None]
    if missing:
        listings_map = find_listings_for_mutations(missing)
        for comp in top:
            if comp.condition is None:
                matched = listings_map.get(comp.id_mutation)
                if matched is not None and matched.condition:
                    comp.condition = matched.condition
                    comp.condition_source = f"listing#{matched.id}"

    p25, median, p75 = _aggregate(target, top)

    result = CompResult(
        target=target,
        comps=top,
        n_comps=len(top),
        median_prix_m2=round(median, 2) if median is not None else None,
        p25_prix_m2=round(p25, 2) if p25 is not None else None,
        p75_prix_m2=round(p75, 2) if p75 is not None else None,
        confidence=_confidence(len(top)),
    )

    if median is not None and p25 is not None and p75 is not None:
        result.suggested_price_low = round(p25 * target.surface, 0)
        result.suggested_price_mid = round(median * target.surface, 0)
        result.suggested_price_high = round(p75 * target.surface, 0)
        verdict = _verdict(target, result.suggested_price_low, result.suggested_price_high)
        result.verdict = verdict or None

    return result
