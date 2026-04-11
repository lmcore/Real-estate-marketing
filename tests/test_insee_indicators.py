"""End-to-end: INSEE + DVF → cross-commune summary with affordability."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
INSEE_SAMPLE = FIXTURES / "sample_insee_dossier_complet_2020.csv"
DVF_SAMPLE = FIXTURES / "sample_dvf_04112.csv"


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


def test_affordability_ratio_math():
    from shadow_tester.insee.indicators import affordability_ratio

    # 320 000 € for a household earning 19 520 € / UC × 1.6 UC = 31 232 €/yr
    # → 320000 / 31232 ≈ 10.25 years
    ratio = affordability_ratio(320_000, 19_520)
    assert ratio == pytest.approx(10.25, rel=1e-2)

    # Null inputs short-circuit.
    assert affordability_ratio(None, 20_000) is None
    assert affordability_ratio(300_000, None) is None
    assert affordability_ratio(300_000, 0) is None


def test_insee_ingest_and_show(isolated_db):
    from shadow_tester.insee.indicators import load_commune
    from shadow_tester.insee.ingest import ingest_from_file

    ingest_from_file(
        INSEE_SAMPLE,
        millesime=2020,
        communes=["04112"],
        source_url=str(INSEE_SAMPLE),
    )
    row = load_commune("04112")
    assert row is not None
    assert row["nom_commune"] == "Manosque"
    assert row["population"] == pytest.approx(22400)
    assert row["densite_hab_km2"] == pytest.approx(392.36, rel=1e-3)
    assert row["revenu_median_uc"] == pytest.approx(19520)


def test_summary_blends_dvf_and_insee(isolated_db):
    """Ingest both fixtures, then build the cross-source summary."""
    from shadow_tester.dvf.ingest import _INSERT_SQL as DVF_INSERT
    from shadow_tester.dvf.parser import clean_dataframe, iter_records, load_csv
    from shadow_tester.insee.indicators import summarize_commune
    from shadow_tester.insee.ingest import ingest_from_file
    from shadow_tester.storage import connect

    # Load DVF.
    cleaned = clean_dataframe(load_csv(DVF_SAMPLE))
    with connect() as conn:
        conn.executemany(DVF_INSERT, list(iter_records(cleaned)))

    # Load INSEE.
    ingest_from_file(
        INSEE_SAMPLE,
        millesime=2020,
        communes=["04112"],
        source_url=str(INSEE_SAMPLE),
    )

    s = summarize_commune("04112")

    assert s.code_commune == "04112"
    assert s.nom_commune == "Manosque"
    assert s.millesime == 2020
    assert s.population == pytest.approx(22400)
    assert s.revenu_median_uc == pytest.approx(19520)

    # DVF side: there are Maisons and Appartements in the fixture for 2023.
    assert s.year_dvf == 2023
    assert s.median_prix_m2_maison is not None
    assert s.median_prix_m2_appartement is not None

    # Affordability: median Maison price 320k / (19520 * 1.6) ~= 10.25 yrs.
    assert s.affordability_years_maison is not None
    assert 8.0 < s.affordability_years_maison < 13.0
