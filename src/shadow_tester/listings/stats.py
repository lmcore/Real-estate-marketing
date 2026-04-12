"""Aggregate listing statistics by property condition.

Answers questions like:
- What is the median negotiation margin for rénovés vs à rénover?
- How long do listings stay on market depending on condition?
- What is the typical €/m² by condition bucket?

Only matched listings (with a DVF link) provide negotiation and delay data.
All listings contribute to asking-price and count stats.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from shadow_tester.storage import connect

logger = logging.getLogger(__name__)


@dataclass
class ConditionBucket:
    """Stats for one condition category."""

    condition: str
    count: int = 0

    # Asking price stats (all listings with this condition).
    median_price_asked: float | None = None
    median_surface: float | None = None
    median_prix_m2_asked: float | None = None

    # DVF-matched stats (only listings with matched_mutation_id).
    matched_count: int = 0
    median_price_delta_pct: float | None = None   # (dvf - asked) / asked × 100
    median_days_to_sale: int | None = None
    median_prix_m2_sold: float | None = None


@dataclass
class ListingStats:
    """Aggregate stats across all condition buckets."""

    commune: str | None
    type_local: str | None
    total_listings: int = 0
    total_matched: int = 0
    buckets: list[ConditionBucket] = field(default_factory=list)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


# ── SQL ──────────────────────────────────────────────────────────────────

_LISTING_SQL = """
SELECT
    l.condition,
    l.price_asked,
    l.surface,
    l.matched_mutation_id,
    l.first_seen,
    d.valeur_fonciere  AS dvf_price,
    d.date_mutation,
    d.surface_reelle_bati AS dvf_surface
FROM listings l
LEFT JOIN dvf_transactions d
    ON l.matched_mutation_id = d.id_mutation
   AND d.disposition = 1
   AND d.row_idx = 0
WHERE 1=1
"""


def compute_listing_stats(
    *,
    commune: str | None = None,
    type_local: str | None = None,
) -> ListingStats:
    """Compute aggregate stats grouped by condition.

    Parameters
    ----------
    commune:
        Filter by INSEE commune code.
    type_local:
        Filter by property type (Maison / Appartement).

    Returns
    -------
    ListingStats with one ConditionBucket per distinct condition found.
    """
    sql = _LISTING_SQL
    params: list[object] = []

    if commune:
        sql += " AND l.commune = ?"
        params.append(commune.zfill(5))
    if type_local:
        sql += " AND l.type_local = ?"
        params.append(type_local)

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    # Accumulate raw values per condition.
    from collections import defaultdict
    from datetime import date

    prices: dict[str, list[float]] = defaultdict(list)
    surfaces: dict[str, list[float]] = defaultdict(list)
    prix_m2_asked: dict[str, list[float]] = defaultdict(list)
    deltas: dict[str, list[float]] = defaultdict(list)
    days: dict[str, list[int]] = defaultdict(list)
    prix_m2_sold: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    matched_counts: dict[str, int] = defaultdict(int)

    for row in rows:
        cond = row["condition"] or "inconnu"
        counts[cond] += 1

        asked = row["price_asked"]
        surf = row["surface"]
        if asked and asked > 0:
            prices[cond].append(asked)
        if surf and surf > 0:
            surfaces[cond].append(surf)
        if asked and asked > 0 and surf and surf > 0:
            prix_m2_asked[cond].append(asked / surf)

        # DVF-matched data.
        dvf_price = row["dvf_price"]
        if dvf_price is not None and row["matched_mutation_id"]:
            matched_counts[cond] += 1

            dvf_surf = row["dvf_surface"]
            if dvf_surf and dvf_surf > 0:
                prix_m2_sold[cond].append(dvf_price / dvf_surf)

            if asked and asked > 0:
                delta = (dvf_price - asked) / asked * 100
                deltas[cond].append(delta)

            # Days to sale.
            first_seen = row["first_seen"]
            mutation_date = row["date_mutation"]
            if first_seen and mutation_date:
                try:
                    d_seen = date.fromisoformat(first_seen[:10])
                    d_mut = date.fromisoformat(mutation_date[:10])
                    gap = (d_mut - d_seen).days
                    if gap >= 0:
                        days[cond].append(gap)
                except ValueError:
                    pass

    # Build buckets.
    all_conditions = sorted(counts.keys())
    buckets = []
    for cond in all_conditions:
        b = ConditionBucket(
            condition=cond,
            count=counts[cond],
            median_price_asked=_median(prices.get(cond, [])),
            median_surface=_median(surfaces.get(cond, [])),
            median_prix_m2_asked=_median(prix_m2_asked.get(cond, [])),
            matched_count=matched_counts.get(cond, 0),
            median_price_delta_pct=_median(deltas.get(cond, [])),
            median_days_to_sale=(
                int(_median([float(d) for d in days.get(cond, [])]) or 0)
                if days.get(cond) else None
            ),
            median_prix_m2_sold=_median(prix_m2_sold.get(cond, [])),
        )
        buckets.append(b)

    return ListingStats(
        commune=commune,
        type_local=type_local,
        total_listings=sum(counts.values()),
        total_matched=sum(matched_counts.values()),
        buckets=buckets,
    )
