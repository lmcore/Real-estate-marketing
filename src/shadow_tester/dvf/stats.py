"""Basic market statistics derived from ingested DVF transactions."""

from __future__ import annotations

from dataclasses import dataclass, field

from shadow_tester.storage import connect


@dataclass
class BucketStats:
    type_local: str
    year: int
    n_transactions: int
    median_prix_m2: float | None
    p25_prix_m2: float | None
    p75_prix_m2: float | None
    median_surface: float | None
    median_valeur: float | None


@dataclass
class CommuneStats:
    commune: str
    total_transactions: int
    buckets: list[BucketStats] = field(default_factory=list)


# SQLite has no percentile_cont; we compute medians / quartiles in Python from
# a single sorted pull. For a single commune, row counts stay small (low
# thousands), so this is perfectly fine.
_FETCH_SQL = """
SELECT year, type_local, prix_m2, surface_reelle_bati, valeur_fonciere
FROM dvf_transactions
WHERE code_commune = ?
  AND type_local IN ('Maison', 'Appartement')
  AND prix_m2 IS NOT NULL
  AND year IS NOT NULL
"""


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    """Linear-interpolation percentile (matches numpy's default)."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = k - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return _percentile(sorted(values), 0.5)


def compute_commune_stats(
    commune: str,
    *,
    type_local: str | None = None,
    year: int | None = None,
) -> CommuneStats:
    """Aggregate DVF stats for a commune, optionally filtered.

    Returns price/m² medians and quartiles per (year, type_local) bucket.
    """
    with connect() as conn:
        rows = conn.execute(_FETCH_SQL, (commune,)).fetchall()

    buckets: dict[tuple[int, str], list[tuple[float, float, float]]] = {}
    for row in rows:
        y = int(row["year"])
        t = row["type_local"]
        if type_local and t != type_local:
            continue
        if year and y != year:
            continue
        buckets.setdefault((y, t), []).append(
            (
                float(row["prix_m2"]),
                float(row["surface_reelle_bati"] or 0),
                float(row["valeur_fonciere"] or 0),
            )
        )

    out_buckets: list[BucketStats] = []
    for (y, t), values in sorted(buckets.items()):
        prix_m2_sorted = sorted(v[0] for v in values)
        surface_sorted = sorted(v[1] for v in values if v[1] > 0)
        valeur_sorted = sorted(v[2] for v in values if v[2] > 0)
        out_buckets.append(
            BucketStats(
                type_local=t,
                year=y,
                n_transactions=len(values),
                median_prix_m2=_percentile(prix_m2_sorted, 0.5),
                p25_prix_m2=_percentile(prix_m2_sorted, 0.25),
                p75_prix_m2=_percentile(prix_m2_sorted, 0.75),
                median_surface=_median(surface_sorted),
                median_valeur=_median(valeur_sorted),
            )
        )

    return CommuneStats(
        commune=commune,
        total_transactions=sum(b.n_transactions for b in out_buckets),
        buckets=out_buckets,
    )
