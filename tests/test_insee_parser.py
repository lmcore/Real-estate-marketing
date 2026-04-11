"""Unit tests for the INSEE parser and the derived indicators."""

from __future__ import annotations

from pathlib import Path

import pytest

from shadow_tester.insee.mapping import DEFAULT_MAPPING
from shadow_tester.insee.parser import (
    load_insee_csv,
    normalise_rows,
)

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "sample_insee_dossier_complet_2020.csv"


@pytest.fixture(scope="module")
def raw_rows():
    return load_insee_csv(SAMPLE)


@pytest.fixture(scope="module")
def manosque_row(raw_rows):
    normalised = list(normalise_rows(raw_rows, millesime=2020))
    return next(r for r in normalised if r["code_commune"] == "04112")


def test_load_insee_csv_zero_pads(raw_rows):
    codes = {r["CODGEO"] for r in raw_rows}
    assert "04112" in codes
    # Must stay 5 chars.
    assert all(len(c) == 5 for c in codes)


def test_load_insee_csv_filters_commune():
    filtered = load_insee_csv(SAMPLE, communes=["04112"])
    assert len(filtered) == 1
    assert filtered[0]["CODGEO"] == "04112"


def test_mapping_placeholder_resolution():
    resolved = DEFAULT_MAPPING.for_year(2020)
    assert resolved.field_map["population"] == ["P20_POP"]
    assert resolved.field_map["revenu_median_uc"] == ["MED20", "MEDIAN20"]
    assert resolved.field_map["logements_total"] == ["P20_LOG"]


def test_normalise_rows_extracts_basic_fields(manosque_row):
    assert manosque_row["nom_commune"] == "Manosque"
    assert manosque_row["code_departement"] == "04"
    assert manosque_row["code_region"] == "93"
    assert manosque_row["millesime"] == 2020
    assert manosque_row["population"] == pytest.approx(22400)
    assert manosque_row["superficie_km2"] == pytest.approx(57.09)
    assert manosque_row["revenu_median_uc"] == pytest.approx(19520)
    assert manosque_row["taux_pauvrete"] == pytest.approx(16.4)


def test_normalise_rows_computes_density(manosque_row):
    # 22400 / 57.09 = 392.4 hab/km²
    assert manosque_row["densite_hab_km2"] == pytest.approx(392.36, rel=1e-3)


def test_normalise_rows_computes_vacancy_rate(manosque_row):
    # 730 / 11020 = 6.62 %
    assert manosque_row["taux_vacance"] == pytest.approx(6.62, rel=1e-3)


def test_normalise_rows_computes_secondary_residence_rate(manosque_row):
    # 310 / 11020 = 2.81 %
    assert manosque_row["taux_residences_sec"] == pytest.approx(2.81, rel=1e-3)


def test_normalise_rows_computes_owner_rate(manosque_row):
    # 5489 / 9980 = 55.00 %
    assert manosque_row["part_proprietaires"] == pytest.approx(55.0, rel=1e-2)


def test_normalise_rows_computes_unemployment_rate(manosque_row):
    # 1408 / 10050 = 14.01 %
    assert manosque_row["taux_chomage_1564"] == pytest.approx(14.01, rel=1e-2)


def test_normalise_rows_temporary_fields_removed(manosque_row):
    # These should not leak into the final record.
    for leaked in ("chom_1564", "pop_1564", "part_proprietaires_rp"):
        assert leaked not in manosque_row
