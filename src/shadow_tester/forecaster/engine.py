"""Forecaster engine — calculates profit margin for buy-renovate-sell scenarios.

Uses the comps engine to estimate resale price, then factors in all MDB costs
(frais notaire, travaux, portage, TVA sur marge, agence) to produce a net
margin and ROI.
"""

from __future__ import annotations

import logging

from shadow_tester.comps.engine import find_comparables
from shadow_tester.comps.models import Target
from shadow_tester.forecaster.models import ForecastParams, ForecastResult

logger = logging.getLogger(__name__)


def _build_target(params: ForecastParams) -> Target:
    """Build a comps Target from forecast params for the *resale* scenario."""
    return Target(
        commune=params.commune,
        type_local=params.type_local,
        surface=params.surface,
        rooms=params.rooms,
        surface_terrain=params.surface_terrain,
        lat=params.lat,
        lon=params.lon,
        address=params.address,
        street_keyword=params.street_keyword,
        radius_km=params.radius_km,
        max_years_old=params.max_years_old,
        limit=params.comps_limit,
    )


def calculate_forecast(params: ForecastParams) -> ForecastResult:
    """Compute the full margin breakdown for a buy-renovate-sell project.

    Steps:
    1. Calculate investment costs (purchase + notaire + travaux + portage).
    2. Use the comps engine to estimate resale price (P25/median/P75).
    3. Deduct TVA sur marge + agency fees.
    4. Return complete breakdown with ROI.
    """
    result = ForecastResult(params=params)

    # ── 1. Investment breakdown ──────────────────────────────────────────
    result.prix_achat = params.prix_achat
    result.frais_notaire = round(params.prix_achat * params.frais_notaire_pct, 2)
    result.travaux = params.travaux

    # Carrying cost: monthly rate × months × (purchase + notaire + travaux).
    base_invest = result.prix_achat + result.frais_notaire + result.travaux
    result.frais_portage = round(
        base_invest * params.portage_mensuel_pct * params.portage_mois, 2
    )
    result.total_investissement = round(
        base_invest + result.frais_portage, 2
    )

    # ── 2. Resale estimate from comps ────────────────────────────────────
    target = _build_target(params)
    comp_result = find_comparables(target)

    result.n_comps = comp_result.n_comps
    result.confidence = comp_result.confidence
    result.prix_m2_median = comp_result.median_prix_m2
    result.prix_revente_low = comp_result.suggested_price_low
    result.prix_revente_mid = comp_result.suggested_price_mid
    result.prix_revente_high = comp_result.suggested_price_high
    result.comps_detail = comp_result.comps

    if result.prix_revente_mid is None:
        logger.warning(
            "No comps found for %s %s %sm² in %s — cannot estimate resale",
            params.type_local, params.surface, params.commune, params.commune,
        )
        result.verdict = "Pas assez de données pour estimer le prix de revente."
        return result

    # ── 3. Margin calculation (median scenario) ──────────────────────────
    _compute_margins(result, result.prix_revente_mid, is_median=True)

    # Low / high scenarios (just marge_nette, not full breakdown).
    if result.prix_revente_low is not None:
        result.marge_nette_low = _net_margin(
            result.prix_revente_low,
            result.total_investissement,
            params,
        )
    if result.prix_revente_high is not None:
        result.marge_nette_high = _net_margin(
            result.prix_revente_high,
            result.total_investissement,
            params,
        )

    # ── 4. Verdict ───────────────────────────────────────────────────────
    result.verdict = _verdict(result)

    return result


def _compute_margins(
    result: ForecastResult,
    prix_revente: float,
    *,
    is_median: bool = False,
) -> None:
    """Fill margin fields on *result* for a given resale price."""
    params = result.params

    # Agency commission (on resale price).
    result.frais_agence = round(prix_revente * params.frais_agence_pct, 2)

    # TVA sur marge: 20% of (resale − purchase), floored at 0.
    plus_value = max(0.0, prix_revente - params.prix_achat)
    result.tva_sur_marge = round(plus_value * params.tva_marge_pct, 2)

    # Gross margin = resale − total investment.
    result.marge_brute = round(prix_revente - result.total_investissement, 2)

    # Net margin = gross − TVA − agency.
    result.marge_nette = round(
        result.marge_brute - result.tva_sur_marge - result.frais_agence, 2
    )

    # ROI = net margin / total investment × 100.
    if result.total_investissement > 0:
        result.roi_pct = round(
            result.marge_nette / result.total_investissement * 100, 2
        )
        # Annualised ROI (simple annualisation).
        if params.portage_mois > 0:
            result.roi_annualise_pct = round(
                result.roi_pct * 12 / params.portage_mois, 2
            )


def _net_margin(
    prix_revente: float,
    total_investissement: float,
    params: ForecastParams,
) -> float:
    """Quick net margin for low/high scenarios (no full breakdown)."""
    agence = prix_revente * params.frais_agence_pct
    plus_value = max(0.0, prix_revente - params.prix_achat)
    tva = plus_value * params.tva_marge_pct
    brute = prix_revente - total_investissement
    return round(brute - tva - agence, 2)


def _verdict(result: ForecastResult) -> str:
    """Qualitative verdict based on ROI and confidence."""
    if result.marge_nette is None or result.roi_pct is None:
        return "Données insuffisantes pour un verdict."

    confidence = result.confidence
    roi = result.roi_pct

    if roi >= 20:
        base = "Excellent projet — marge nette > 20 %."
    elif roi >= 10:
        base = "Bon projet — marge nette correcte (10–20 %)."
    elif roi >= 5:
        base = "Projet viable mais serré — marge nette 5–10 %, peu de marge d'erreur."
    elif roi >= 0:
        base = "Projet à risque — marge nette < 5 %, vulnérable aux imprévus."
    else:
        base = "Projet déficitaire — marge nette négative, à éviter."

    if confidence == "low":
        base += " Attention : confiance faible (peu de comparables)."
    elif confidence == "medium":
        base += " Confiance moyenne — vérifier avec des données terrain."

    return base
