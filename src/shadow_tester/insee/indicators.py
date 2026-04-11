"""Derived market-tension indicators built on top of DVF + INSEE.

These are computed on demand from SQLite — they are not persisted, so the
numbers always reflect the current state of ingested data.
"""

from __future__ import annotations

from dataclasses import dataclass

from shadow_tester.dvf.stats import compute_commune_stats
from shadow_tester.storage import connect


@dataclass
class CommuneSummary:
    """A one-shot snapshot of a commune's market, blending DVF + INSEE."""

    code_commune: str
    nom_commune: str | None
    millesime: int | None
    population: float | None
    densite_hab_km2: float | None
    taux_vacance: float | None
    taux_residences_sec: float | None
    part_proprietaires: float | None
    revenu_median_uc: float | None
    taux_chomage_1564: float | None

    # DVF side (latest year with enough data)
    year_dvf: int | None
    median_prix_m2_maison: float | None
    median_prix_m2_appartement: float | None
    median_valeur_maison: float | None
    median_valeur_appartement: float | None
    n_transactions: int

    # Cross-indicators
    affordability_years_maison: float | None
    affordability_years_appartement: float | None


def load_commune(code_commune: str) -> dict[str, object] | None:
    """Fetch the most recent INSEE row for ``code_commune``."""
    with connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM insee_commune
            WHERE code_commune = ?
            ORDER BY millesime DESC
            LIMIT 1
            """,
            (code_commune,),
        ).fetchone()
    return dict(row) if row else None


def affordability_ratio(
    median_price_total: float | None,
    median_income_uc: float | None,
    uc_per_household: float = 1.6,
) -> float | None:
    """Return the number of median household-years needed to buy the bien.

    We use ``uc_per_household`` to convert the income, which is published *per
    unité de consommation* (UC), into an approximate household income. 1.6 UC
    per household is the French average (INSEE DGI 2020).
    """
    if not median_price_total or not median_income_uc:
        return None
    household_income = median_income_uc * uc_per_household
    if household_income <= 0:
        return None
    return round(median_price_total / household_income, 2)


def summarize_commune(code_commune: str) -> CommuneSummary:
    """Blend DVF medians with INSEE demographics for one commune."""
    insee = load_commune(code_commune) or {}
    stats = compute_commune_stats(code_commune)

    # Use the most recent year present in DVF for this commune.
    latest_year: int | None = None
    maison = appartement = None
    if stats.buckets:
        latest_year = max(b.year for b in stats.buckets)
        maison = next(
            (b for b in stats.buckets if b.year == latest_year and b.type_local == "Maison"),
            None,
        )
        appartement = next(
            (b for b in stats.buckets if b.year == latest_year and b.type_local == "Appartement"),
            None,
        )

    revenu = insee.get("revenu_median_uc")  # type: ignore[assignment]
    return CommuneSummary(
        code_commune=code_commune,
        nom_commune=insee.get("nom_commune"),  # type: ignore[arg-type]
        millesime=insee.get("millesime"),  # type: ignore[arg-type]
        population=insee.get("population"),  # type: ignore[arg-type]
        densite_hab_km2=insee.get("densite_hab_km2"),  # type: ignore[arg-type]
        taux_vacance=insee.get("taux_vacance"),  # type: ignore[arg-type]
        taux_residences_sec=insee.get("taux_residences_sec"),  # type: ignore[arg-type]
        part_proprietaires=insee.get("part_proprietaires"),  # type: ignore[arg-type]
        revenu_median_uc=revenu,  # type: ignore[arg-type]
        taux_chomage_1564=insee.get("taux_chomage_1564"),  # type: ignore[arg-type]
        year_dvf=latest_year,
        median_prix_m2_maison=maison.median_prix_m2 if maison else None,
        median_prix_m2_appartement=appartement.median_prix_m2 if appartement else None,
        median_valeur_maison=maison.median_valeur if maison else None,
        median_valeur_appartement=appartement.median_valeur if appartement else None,
        n_transactions=stats.total_transactions,
        affordability_years_maison=affordability_ratio(
            maison.median_valeur if maison else None, revenu  # type: ignore[arg-type]
        ),
        affordability_years_appartement=affordability_ratio(
            appartement.median_valeur if appartement else None, revenu  # type: ignore[arg-type]
        ),
    )
