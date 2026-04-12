"""Tests for the forecaster module — profit-margin calculation for MDB projects."""

from __future__ import annotations

import pytest

from shadow_tester.forecaster.models import (
    DEFAULT_FRAIS_NOTAIRE_PCT,
    DEFAULT_PORTAGE_MENSUEL_PCT,
    DEFAULT_TVA_MARGE_PCT,
    ForecastParams,
    ForecastResult,
)

# ── Model validation tests ───────────────────────────────────────────────


def test_params_validates_positive_prix_achat():
    with pytest.raises(ValueError, match="positive"):
        ForecastParams(
            commune="04112", type_local="Maison", surface=100, prix_achat=-1
        )


def test_params_validates_positive_surface():
    with pytest.raises(ValueError, match="positive"):
        ForecastParams(
            commune="04112", type_local="Maison", surface=0, prix_achat=200_000
        )


def test_params_validates_type_local():
    with pytest.raises(ValueError, match="Unsupported"):
        ForecastParams(
            commune="04112", type_local="Chateau", surface=100, prix_achat=200_000
        )


def test_params_validates_travaux_non_negative():
    with pytest.raises(ValueError, match="Travaux"):
        ForecastParams(
            commune="04112",
            type_local="Maison",
            surface=100,
            prix_achat=200_000,
            travaux=-5000,
        )


def test_params_zero_pads_commune():
    p = ForecastParams(
        commune="4112", type_local="Maison", surface=100, prix_achat=200_000
    )
    assert p.commune == "04112"


def test_params_defaults():
    p = ForecastParams(
        commune="04112", type_local="Maison", surface=100, prix_achat=200_000
    )
    assert p.frais_notaire_pct == DEFAULT_FRAIS_NOTAIRE_PCT
    assert p.tva_marge_pct == DEFAULT_TVA_MARGE_PCT
    assert p.portage_mensuel_pct == DEFAULT_PORTAGE_MENSUEL_PCT
    assert p.portage_mois == 12
    assert p.travaux == 0.0


# ── Pure margin calculation tests (no DB) ────────────────────────────────

# We test the engine's _compute_margins and _net_margin directly by importing
# them — they're pure functions that don't touch the database.


def test_compute_margins_basic():
    """Verify the full margin breakdown for a simple scenario."""
    from shadow_tester.forecaster.engine import _compute_margins

    params = ForecastParams(
        commune="04112",
        type_local="Maison",
        surface=100,
        prix_achat=200_000,
        travaux=50_000,
        portage_mois=12,
        portage_mensuel_pct=0.005,
        frais_notaire_pct=0.025,
        tva_marge_pct=0.20,
        frais_agence_pct=0.0,
    )
    result = ForecastResult(params=params)

    # Manual calculation:
    # frais_notaire = 200_000 * 0.025 = 5_000
    # base_invest = 200_000 + 5_000 + 50_000 = 255_000
    # portage = 255_000 * 0.005 * 12 = 15_300
    # total_invest = 255_000 + 15_300 = 270_300
    result.prix_achat = params.prix_achat
    result.frais_notaire = 5_000.0
    result.travaux = 50_000.0
    result.frais_portage = 15_300.0
    result.total_investissement = 270_300.0

    prix_revente = 320_000.0
    _compute_margins(result, prix_revente)

    # TVA sur marge = (320_000 - 200_000) * 0.20 = 24_000
    assert result.tva_sur_marge == pytest.approx(24_000.0)
    # Marge brute = 320_000 - 270_300 = 49_700
    assert result.marge_brute == pytest.approx(49_700.0)
    # Marge nette = 49_700 - 24_000 - 0 = 25_700
    assert result.marge_nette == pytest.approx(25_700.0)
    # ROI = 25_700 / 270_300 * 100 ≈ 9.51%
    assert result.roi_pct == pytest.approx(9.51, abs=0.1)
    # Annualised ROI (12 months holding = 1 year) = same as ROI
    assert result.roi_annualise_pct == pytest.approx(result.roi_pct, rel=0.01)


def test_compute_margins_with_agency():
    """Agency commission reduces net margin."""
    from shadow_tester.forecaster.engine import _compute_margins

    params = ForecastParams(
        commune="04112",
        type_local="Maison",
        surface=100,
        prix_achat=200_000,
        travaux=0,
        frais_agence_pct=0.05,
        portage_mois=6,
        portage_mensuel_pct=0.005,
        frais_notaire_pct=0.025,
    )
    result = ForecastResult(params=params)
    result.prix_achat = 200_000.0
    result.total_investissement = 210_150.0  # approx with portage

    prix_revente = 250_000.0
    _compute_margins(result, prix_revente)

    # Agency = 250_000 * 0.05 = 12_500
    assert result.frais_agence == pytest.approx(12_500.0)
    # Net includes TVA + agency deduction.
    assert result.marge_nette < result.marge_brute


def test_compute_margins_negative_margin():
    """A bad deal should produce negative margin."""
    from shadow_tester.forecaster.engine import _compute_margins

    params = ForecastParams(
        commune="04112",
        type_local="Maison",
        surface=100,
        prix_achat=300_000,
        travaux=80_000,
    )
    result = ForecastResult(params=params)
    result.prix_achat = 300_000.0
    result.total_investissement = 420_000.0

    # Resale below investment.
    _compute_margins(result, 350_000.0)
    assert result.marge_brute < 0
    assert result.marge_nette < 0


def test_net_margin_shortcut():
    """_net_margin gives the same result as _compute_margins for net."""
    from shadow_tester.forecaster.engine import _compute_margins, _net_margin

    params = ForecastParams(
        commune="04112",
        type_local="Maison",
        surface=100,
        prix_achat=200_000,
        travaux=50_000,
        frais_agence_pct=0.03,
    )
    result = ForecastResult(params=params)
    result.prix_achat = 200_000.0
    result.total_investissement = 270_000.0

    prix_revente = 310_000.0

    _compute_margins(result, prix_revente)
    quick = _net_margin(prix_revente, result.total_investissement, params)
    assert quick == pytest.approx(result.marge_nette)


def test_tva_floored_at_zero():
    """TVA sur marge should be 0 when resale < purchase (no plus-value)."""
    from shadow_tester.forecaster.engine import _compute_margins

    params = ForecastParams(
        commune="04112",
        type_local="Maison",
        surface=100,
        prix_achat=300_000,
    )
    result = ForecastResult(params=params)
    result.prix_achat = 300_000.0
    result.total_investissement = 310_000.0

    _compute_margins(result, 280_000.0)  # resale < purchase
    assert result.tva_sur_marge == 0.0


def test_annualised_roi_6_months():
    """6-month holding should roughly double the annualised ROI vs 12-month."""
    from shadow_tester.forecaster.engine import _compute_margins

    params_12m = ForecastParams(
        commune="04112",
        type_local="Maison",
        surface=100,
        prix_achat=200_000,
        portage_mois=12,
    )
    params_6m = ForecastParams(
        commune="04112",
        type_local="Maison",
        surface=100,
        prix_achat=200_000,
        portage_mois=6,
    )

    result_12 = ForecastResult(params=params_12m)
    result_12.prix_achat = 200_000.0
    result_12.total_investissement = 215_000.0
    _compute_margins(result_12, 280_000.0)

    result_6 = ForecastResult(params=params_6m)
    result_6.prix_achat = 200_000.0
    result_6.total_investissement = 215_000.0
    _compute_margins(result_6, 280_000.0)

    # Same absolute ROI, but 6m annualised = 2x of 12m annualised.
    assert result_6.roi_pct == pytest.approx(result_12.roi_pct)
    assert result_6.roi_annualise_pct == pytest.approx(
        result_12.roi_annualise_pct * 2, rel=0.01
    )


# ── Verdict tests ────────────────────────────────────────────────────────


def test_verdict_excellent():
    from shadow_tester.forecaster.engine import _verdict

    r = ForecastResult(
        params=ForecastParams(
            commune="04112", type_local="Maison", surface=100, prix_achat=200_000
        ),
        marge_nette=50_000.0,
        roi_pct=25.0,
        confidence="high",
    )
    assert "Excellent" in _verdict(r)


def test_verdict_deficit():
    from shadow_tester.forecaster.engine import _verdict

    r = ForecastResult(
        params=ForecastParams(
            commune="04112", type_local="Maison", surface=100, prix_achat=200_000
        ),
        marge_nette=-10_000.0,
        roi_pct=-5.0,
        confidence="high",
    )
    v = _verdict(r)
    assert "déficitaire" in v.lower()


def test_verdict_low_confidence_warning():
    from shadow_tester.forecaster.engine import _verdict

    r = ForecastResult(
        params=ForecastParams(
            commune="04112", type_local="Maison", surface=100, prix_achat=200_000
        ),
        marge_nette=20_000.0,
        roi_pct=10.0,
        confidence="low",
    )
    assert "faible" in _verdict(r).lower()


# ── Integration test with seeded DB ──────────────────────────────────────


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.sqlite"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    from shadow_tester import config as cfg

    monkeypatch.setenv("SHADOW_DB_PATH", str(db_path))
    monkeypatch.setenv("SHADOW_CACHE_DIR", str(cache_dir))
    cfg._settings = None
    yield db_path
    cfg._settings = None


_INSERT_SQL = """
INSERT OR REPLACE INTO dvf_transactions (
    id_mutation, disposition, row_idx,
    date_mutation, nature_mutation, valeur_fonciere,
    code_postal, code_commune, nom_commune, code_departement,
    type_local, surface_reelle_bati, nombre_pieces_principales, surface_terrain,
    adresse_numero, adresse_nom_voie, id_parcelle,
    longitude, latitude,
    prix_m2, year
) VALUES (
    :id_mutation, 1, 0,
    :date_mutation, 'Vente', :valeur_fonciere,
    '04100', '04112', 'Manosque', '04',
    :type_local, :surface, :rooms, NULL,
    :num, :voie, NULL,
    :lon, :lat,
    :prix_m2, :year
)
"""


def _seed(db_path):
    from shadow_tester.storage import connect

    rows = [
        {"id_mutation": "f1", "date_mutation": "2024-03-10", "valeur_fonciere": 270_000,
         "type_local": "Maison", "surface": 100, "rooms": 4,
         "num": "12", "voie": "RUE DES ALPES", "prix_m2": 2700, "year": 2024,
         "lat": 43.830, "lon": 5.784},
        {"id_mutation": "f2", "date_mutation": "2024-05-18", "valeur_fonciere": 295_000,
         "type_local": "Maison", "surface": 110, "rooms": 5,
         "num": "24", "voie": "RUE DES ALPES", "prix_m2": 2682, "year": 2024,
         "lat": 43.831, "lon": 5.785},
        {"id_mutation": "f3", "date_mutation": "2024-07-01", "valeur_fonciere": 250_000,
         "type_local": "Maison", "surface": 95, "rooms": 4,
         "num": "8", "voie": "AV JEAN GIONO", "prix_m2": 2632, "year": 2024,
         "lat": 43.831, "lon": 5.790},
        {"id_mutation": "f4", "date_mutation": "2023-09-15", "valeur_fonciere": 260_000,
         "type_local": "Maison", "surface": 105, "rooms": 4,
         "num": "3", "voie": "CHEMIN DE LA THOMASSINE", "prix_m2": 2476, "year": 2023,
         "lat": 43.841, "lon": 5.765},
        {"id_mutation": "f5", "date_mutation": "2024-01-20", "valeur_fonciere": 280_000,
         "type_local": "Maison", "surface": 100, "rooms": 4,
         "num": "15", "voie": "RUE DES ALPES", "prix_m2": 2800, "year": 2024,
         "lat": 43.830, "lon": 5.784},
    ]
    with connect() as conn:
        conn.executemany(_INSERT_SQL, rows)


def test_calculate_forecast_integration(isolated_db):
    """Full integration: seeded DB → calculate_forecast → margin result."""
    from shadow_tester.forecaster import ForecastParams, calculate_forecast

    _seed(isolated_db)

    params = ForecastParams(
        commune="04112",
        type_local="Maison",
        surface=100,
        prix_achat=200_000,
        travaux=50_000,
        rooms=4,
        portage_mois=12,
        portage_mensuel_pct=0.005,
        frais_notaire_pct=0.025,
        tva_marge_pct=0.20,
        frais_agence_pct=0.0,
    )
    result = calculate_forecast(params)

    # Should find comps.
    assert result.n_comps >= 3
    assert result.prix_revente_mid is not None
    assert result.prix_m2_median is not None

    # Investment breakdown is correct.
    assert result.prix_achat == 200_000.0
    assert result.travaux == 50_000.0
    assert result.frais_notaire == pytest.approx(5_000.0)
    assert result.total_investissement > 255_000  # base + portage

    # Margins are populated.
    assert result.marge_brute is not None
    assert result.marge_nette is not None
    assert result.roi_pct is not None

    # Low/high scenarios.
    assert result.marge_nette_low is not None
    assert result.marge_nette_high is not None
    assert result.marge_nette_low <= result.marge_nette <= result.marge_nette_high

    # Verdict is set.
    assert result.verdict is not None
    assert len(result.verdict) > 10


def test_calculate_forecast_no_comps(isolated_db):
    """With an empty commune, the forecast should gracefully return no-data verdict."""
    from shadow_tester.forecaster import ForecastParams, calculate_forecast

    _seed(isolated_db)

    params = ForecastParams(
        commune="99999",
        type_local="Maison",
        surface=100,
        prix_achat=200_000,
    )
    result = calculate_forecast(params)

    assert result.prix_revente_mid is None
    assert result.marge_nette is None
    assert result.verdict is not None
    assert "données" in result.verdict.lower()


def test_calculate_forecast_with_good_deal(isolated_db):
    """A very cheap acquisition should produce positive ROI."""
    from shadow_tester.forecaster import ForecastParams, calculate_forecast

    _seed(isolated_db)

    params = ForecastParams(
        commune="04112",
        type_local="Maison",
        surface=100,
        prix_achat=100_000,  # well below market
        travaux=30_000,
        rooms=4,
    )
    result = calculate_forecast(params)
    assert result.marge_nette is not None
    assert result.marge_nette > 0
    assert result.roi_pct > 0


# ── Repo tests ───────────────────────────────────────────────────────────


def test_save_and_get_forecast(isolated_db):
    """Round-trip: save → get → verify fields."""
    from shadow_tester.forecaster import (
        ForecastParams,
        calculate_forecast,
        get_forecast,
        save_forecast,
    )

    _seed(isolated_db)

    params = ForecastParams(
        commune="04112",
        type_local="Maison",
        surface=100,
        prix_achat=200_000,
        travaux=50_000,
        label="Test scenario",
    )
    result = calculate_forecast(params)
    saved = save_forecast(result)
    assert saved.id is not None
    assert saved.created_at is not None

    loaded = get_forecast(saved.id)
    assert loaded is not None
    assert loaded.params.commune == "04112"
    assert loaded.params.label == "Test scenario"
    assert loaded.prix_achat == pytest.approx(saved.prix_achat)
    assert loaded.marge_nette == pytest.approx(saved.marge_nette)
    assert loaded.roi_pct == pytest.approx(saved.roi_pct)


def test_list_forecasts(isolated_db):
    from shadow_tester.forecaster import (
        ForecastParams,
        calculate_forecast,
        list_forecasts,
        save_forecast,
    )

    _seed(isolated_db)

    for label in ["Scenario A", "Scenario B"]:
        p = ForecastParams(
            commune="04112", type_local="Maison", surface=100,
            prix_achat=200_000, label=label,
        )
        save_forecast(calculate_forecast(p))

    all_fc = list_forecasts()
    assert len(all_fc) == 2

    filtered = list_forecasts(commune="99999")
    assert len(filtered) == 0


def test_delete_forecast(isolated_db):
    from shadow_tester.forecaster import (
        ForecastParams,
        calculate_forecast,
        delete_forecast,
        get_forecast,
        save_forecast,
    )

    _seed(isolated_db)

    p = ForecastParams(
        commune="04112", type_local="Maison", surface=100, prix_achat=200_000,
    )
    saved = save_forecast(calculate_forecast(p))
    assert get_forecast(saved.id) is not None

    assert delete_forecast(saved.id) is True
    assert get_forecast(saved.id) is None

    # Deleting again returns False.
    assert delete_forecast(saved.id) is False
