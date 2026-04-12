"""SQLite persistence for saved forecast scenarios."""

from __future__ import annotations

import sqlite3

from shadow_tester.forecaster.models import ForecastParams, ForecastResult
from shadow_tester.storage import connect


def save_forecast(result: ForecastResult) -> ForecastResult:
    """Persist a forecast result and return it with ``id`` and ``created_at`` set."""
    p = result.params
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO forecasts (
                label, commune, type_local, surface, rooms, surface_terrain,
                lat, lon,
                prix_achat, travaux, condition_achat, condition_revente,
                frais_notaire_pct, tva_marge_pct, portage_mois,
                portage_mensuel_pct, frais_agence_pct,
                prix_revente_low, prix_revente_mid, prix_revente_high,
                prix_m2_median, n_comps, confidence,
                frais_notaire, frais_portage, total_investissement,
                frais_agence, tva_sur_marge, marge_brute, marge_nette,
                marge_nette_low, marge_nette_high,
                roi_pct, roi_annualise_pct, verdict
            ) VALUES (
                :label, :commune, :type_local, :surface, :rooms, :surface_terrain,
                :lat, :lon,
                :prix_achat, :travaux, :condition_achat, :condition_revente,
                :frais_notaire_pct, :tva_marge_pct, :portage_mois,
                :portage_mensuel_pct, :frais_agence_pct,
                :prix_revente_low, :prix_revente_mid, :prix_revente_high,
                :prix_m2_median, :n_comps, :confidence,
                :frais_notaire, :frais_portage, :total_investissement,
                :frais_agence, :tva_sur_marge, :marge_brute, :marge_nette,
                :marge_nette_low, :marge_nette_high,
                :roi_pct, :roi_annualise_pct, :verdict
            )
            """,
            {
                "label": p.label,
                "commune": p.commune,
                "type_local": p.type_local,
                "surface": p.surface,
                "rooms": p.rooms,
                "surface_terrain": p.surface_terrain,
                "lat": p.lat,
                "lon": p.lon,
                "prix_achat": result.prix_achat,
                "travaux": result.travaux,
                "condition_achat": p.condition_achat,
                "condition_revente": p.condition_revente,
                "frais_notaire_pct": p.frais_notaire_pct,
                "tva_marge_pct": p.tva_marge_pct,
                "portage_mois": p.portage_mois,
                "portage_mensuel_pct": p.portage_mensuel_pct,
                "frais_agence_pct": p.frais_agence_pct,
                "prix_revente_low": result.prix_revente_low,
                "prix_revente_mid": result.prix_revente_mid,
                "prix_revente_high": result.prix_revente_high,
                "prix_m2_median": result.prix_m2_median,
                "n_comps": result.n_comps,
                "confidence": result.confidence,
                "frais_notaire": result.frais_notaire,
                "frais_portage": result.frais_portage,
                "total_investissement": result.total_investissement,
                "frais_agence": result.frais_agence,
                "tva_sur_marge": result.tva_sur_marge,
                "marge_brute": result.marge_brute,
                "marge_nette": result.marge_nette,
                "marge_nette_low": result.marge_nette_low,
                "marge_nette_high": result.marge_nette_high,
                "roi_pct": result.roi_pct,
                "roi_annualise_pct": result.roi_annualise_pct,
                "verdict": result.verdict,
            },
        )
        result.id = cur.lastrowid
        row = conn.execute(
            "SELECT created_at FROM forecasts WHERE id = ?", (result.id,)
        ).fetchone()
        if row:
            result.created_at = row["created_at"]
    return result


def _row_to_result(row: sqlite3.Row) -> ForecastResult:
    """Reconstruct a ForecastResult from a DB row."""
    params = ForecastParams(
        commune=row["commune"],
        type_local=row["type_local"],
        surface=float(row["surface"]),
        prix_achat=float(row["prix_achat"]),
        rooms=int(row["rooms"]) if row["rooms"] is not None else None,
        surface_terrain=(
            float(row["surface_terrain"]) if row["surface_terrain"] is not None else None
        ),
        lat=float(row["lat"]) if row["lat"] is not None else None,
        lon=float(row["lon"]) if row["lon"] is not None else None,
        travaux=float(row["travaux"]),
        condition_achat=row["condition_achat"] or "a_renover",
        condition_revente=row["condition_revente"] or "renove",
        frais_notaire_pct=float(row["frais_notaire_pct"]) if row["frais_notaire_pct"] is not None else 0.025,
        tva_marge_pct=float(row["tva_marge_pct"]) if row["tva_marge_pct"] is not None else 0.20,
        portage_mois=int(row["portage_mois"]) if row["portage_mois"] is not None else 12,
        portage_mensuel_pct=float(row["portage_mensuel_pct"]) if row["portage_mensuel_pct"] is not None else 0.005,
        frais_agence_pct=float(row["frais_agence_pct"]) if row["frais_agence_pct"] is not None else 0.0,
        label=row["label"],
    )
    r = ForecastResult(params=params)
    r.id = int(row["id"])
    r.created_at = row["created_at"]
    r.prix_achat = float(row["prix_achat"])
    r.travaux = float(row["travaux"])
    r.frais_notaire = float(row["frais_notaire"]) if row["frais_notaire"] is not None else 0.0
    r.frais_portage = float(row["frais_portage"]) if row["frais_portage"] is not None else 0.0
    r.total_investissement = float(row["total_investissement"]) if row["total_investissement"] is not None else 0.0
    r.prix_revente_low = float(row["prix_revente_low"]) if row["prix_revente_low"] is not None else None
    r.prix_revente_mid = float(row["prix_revente_mid"]) if row["prix_revente_mid"] is not None else None
    r.prix_revente_high = float(row["prix_revente_high"]) if row["prix_revente_high"] is not None else None
    r.prix_m2_median = float(row["prix_m2_median"]) if row["prix_m2_median"] is not None else None
    r.n_comps = int(row["n_comps"]) if row["n_comps"] is not None else 0
    r.confidence = row["confidence"] or "low"
    r.frais_agence = float(row["frais_agence"]) if row["frais_agence"] is not None else 0.0
    r.tva_sur_marge = float(row["tva_sur_marge"]) if row["tva_sur_marge"] is not None else 0.0
    r.marge_brute = float(row["marge_brute"]) if row["marge_brute"] is not None else None
    r.marge_nette = float(row["marge_nette"]) if row["marge_nette"] is not None else None
    r.marge_nette_low = float(row["marge_nette_low"]) if row["marge_nette_low"] is not None else None
    r.marge_nette_high = float(row["marge_nette_high"]) if row["marge_nette_high"] is not None else None
    r.roi_pct = float(row["roi_pct"]) if row["roi_pct"] is not None else None
    r.roi_annualise_pct = float(row["roi_annualise_pct"]) if row["roi_annualise_pct"] is not None else None
    r.verdict = row["verdict"]
    return r


def get_forecast(forecast_id: int) -> ForecastResult | None:
    """Load a single saved forecast by ID."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM forecasts WHERE id = ?", (forecast_id,)
        ).fetchone()
    return _row_to_result(row) if row else None


def list_forecasts(*, commune: str | None = None) -> list[ForecastResult]:
    """List saved forecasts, optionally filtered by commune."""
    sql = "SELECT * FROM forecasts"
    params: dict[str, str] = {}
    if commune:
        sql += " WHERE commune = :commune"
        params["commune"] = commune.zfill(5)
    sql += " ORDER BY created_at DESC"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_result(r) for r in rows]


def delete_forecast(forecast_id: int) -> bool:
    """Delete a saved forecast. Returns True if a row was deleted."""
    with connect() as conn:
        cur = conn.execute("DELETE FROM forecasts WHERE id = ?", (forecast_id,))
    return cur.rowcount > 0
