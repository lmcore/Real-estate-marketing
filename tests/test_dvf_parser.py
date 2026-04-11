"""Unit tests for the DVF parser and the derived stats."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from shadow_tester.dvf.parser import (
    BUILT_LOCAL_TYPES,
    clean_dataframe,
    iter_records,
    load_csv,
)

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "sample_dvf_04112.csv"


@pytest.fixture(scope="module")
def raw_df() -> pd.DataFrame:
    return load_csv(SAMPLE)


@pytest.fixture(scope="module")
def cleaned(raw_df: pd.DataFrame) -> pd.DataFrame:
    return clean_dataframe(raw_df)


def test_load_csv_keeps_expected_columns(raw_df: pd.DataFrame) -> None:
    expected = {
        "id_mutation",
        "date_mutation",
        "valeur_fonciere",
        "code_commune",
        "type_local",
        "surface_reelle_bati",
    }
    assert expected.issubset(raw_df.columns)


def test_clean_drops_adjudications(cleaned: pd.DataFrame) -> None:
    # Row "2023-5" is an Adjudication, must be filtered out.
    assert "2023-5" not in cleaned["id_mutation"].tolist()


def test_clean_keeps_vente_rows(cleaned: pd.DataFrame) -> None:
    # 6 venteS, 1 adjudication → 6 rows expected.
    assert len(cleaned) == 6
    assert set(cleaned["nature_mutation"].unique()) == {"Vente"}


def test_numeric_coercion(cleaned: pd.DataFrame) -> None:
    # valeur_fonciere uses "," as decimal separator in the raw file.
    assert cleaned["valeur_fonciere"].dtype.kind == "f"
    # 95 000 € = land sale (2023-4), 425 000 € = biggest house (2023-6).
    assert cleaned["valeur_fonciere"].min() == pytest.approx(95000.0)
    assert cleaned["valeur_fonciere"].max() == pytest.approx(425000.0)


def test_prix_m2_computed_only_for_built_locals(cleaned: pd.DataFrame) -> None:
    # The "terrain" row (id=2023-4) has no type_local: prix_m2 must be NULL.
    terrain = cleaned[cleaned["id_mutation"] == "2023-4"]
    if not terrain.empty:
        assert terrain["prix_m2"].isna().all()

    # Maison 250 000€ / 95 m² = 2631.58 €/m²
    maison = cleaned[cleaned["id_mutation"] == "2023-1"].iloc[0]
    assert maison["type_local"] in BUILT_LOCAL_TYPES
    assert maison["prix_m2"] == pytest.approx(2631.58, rel=1e-3)


def test_year_column(cleaned: pd.DataFrame) -> None:
    assert set(cleaned["year"].dropna().astype(int).tolist()) == {2023}


def test_code_commune_zero_padded(cleaned: pd.DataFrame) -> None:
    assert (cleaned["code_commune"] == "04112").all()


def test_iter_records_yields_sqlite_compatible_dicts(cleaned: pd.DataFrame) -> None:
    records = list(iter_records(cleaned))
    assert records, "iter_records produced no rows"

    # All required keys must be present.
    required = {
        "id_mutation",
        "disposition",
        "row_idx",
        "date_mutation",
        "valeur_fonciere",
        "code_commune",
        "prix_m2",
        "year",
    }
    assert required.issubset(records[0].keys())

    # None (not pd.NA) for nullable fields so sqlite3 binds correctly.
    for rec in records:
        for k, v in rec.items():
            assert v is None or not isinstance(v, float) or not _isnan(v), (
                f"NaN leaked into record field {k}: {rec}"
            )


def _isnan(x: float) -> bool:
    return x != x
