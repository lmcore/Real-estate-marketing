"""End-to-end test of comps.engine with a seeded SQLite database."""

from __future__ import annotations

import pytest


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


# Hand-crafted Manosque transactions spanning several streets, sizes and years.
# Coordinates are realistic-ish for Manosque centre.
_SEED_ROWS = [
    # (id, disposition, row_idx, date, valeur, code_postal, commune, type_local,
    #  surface, rooms, voie, adresse_numero, prix_m2, year, lat, lon)
    ("m1", 1, 0, "2024-03-10", 270_000, "04100", "04112", "Maison",      100, 4, "RUE DES ALPES",            "12", 2700.0, 2024, 43.8300, 5.7846),
    ("m2", 1, 0, "2024-05-18", 295_000, "04100", "04112", "Maison",      110, 5, "RUE DES ALPES",            "24", 2681.8, 2024, 43.8305, 5.7850),
    ("m3", 1, 0, "2023-11-02", 320_000, "04100", "04112", "Maison",      140, 5, "CHEMIN DE LA THOMASSINE",  "3",  2285.7, 2023, 43.8410, 5.7650),
    ("m4", 1, 0, "2024-01-22", 410_000, "04100", "04112", "Maison",      160, 6, "ROUTE DE VOLX",            "30", 2562.5, 2024, 43.8450, 5.7700),
    ("m5", 1, 0, "2022-07-14", 215_000, "04100", "04112", "Maison",      85,  3, "RUE DES ALPES",            "45", 2529.4, 2022, 43.8295, 5.7840),
    ("m6", 1, 0, "2018-06-10", 180_000, "04100", "04112", "Maison",      95,  4, "RUE DES ALPES",            "60", 1894.7, 2018, 43.8299, 5.7848),  # too old
    ("m7", 1, 0, "2024-09-05", 250_000, "04100", "04112", "Maison",      90,  4, "AVENUE JEAN GIONO",        "8",  2777.8, 2024, 43.8312, 5.7901),
    ("a1", 1, 0, "2024-02-12", 190_000, "04100", "04112", "Appartement", 65,  3, "BOULEVARD MARTIN BRET",    "15", 2923.0, 2024, 43.8305, 5.7885),
    ("a2", 1, 0, "2024-04-03", 220_000, "04100", "04112", "Appartement", 72,  3, "BOULEVARD MARTIN BRET",    "20", 3055.5, 2024, 43.8308, 5.7889),
]

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
    :id_mutation, :disposition, :row_idx,
    :date_mutation, 'Vente', :valeur_fonciere,
    :code_postal, :code_commune, 'Manosque', '04',
    :type_local, :surface_reelle_bati, :nombre_pieces_principales, NULL,
    :adresse_numero, :adresse_nom_voie, NULL,
    :longitude, :latitude,
    :prix_m2, :year
)
"""


def _seed(db_path):
    from shadow_tester.storage import connect

    records = []
    for row in _SEED_ROWS:
        records.append(
            {
                "id_mutation": row[0],
                "disposition": row[1],
                "row_idx": row[2],
                "date_mutation": row[3],
                "valeur_fonciere": row[4],
                "code_postal": row[5],
                "code_commune": row[6],
                "type_local": row[7],
                "surface_reelle_bati": row[8],
                "nombre_pieces_principales": row[9],
                "adresse_nom_voie": row[10],
                "adresse_numero": row[11],
                "prix_m2": row[12],
                "year": row[13],
                "latitude": row[14],
                "longitude": row[15],
            }
        )
    with connect() as conn:
        conn.executemany(_INSERT_SQL, records)


_INSERT_TERRAIN_SQL = """
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
    :type_local, :surface, :rooms, :surface_terrain,
    :num, :voie, NULL,
    :lon, :lat,
    :prix_m2, :year
)
"""


def _seed_with_terrain(db_path):
    """Seed with terrain data for Maison rows."""
    from shadow_tester.storage import connect

    rows = [
        {"id_mutation": "mt1", "date_mutation": "2024-03-10", "valeur_fonciere": 270_000,
         "type_local": "Maison", "surface": 100, "rooms": 4, "surface_terrain": 500,
         "num": "12", "voie": "RUE DES ALPES", "prix_m2": 2700, "year": 2024,
         "lat": 43.830, "lon": 5.784},
        {"id_mutation": "mt2", "date_mutation": "2024-05-18", "valeur_fonciere": 350_000,
         "type_local": "Maison", "surface": 110, "rooms": 5, "surface_terrain": 1200,
         "num": "24", "voie": "RUE DES ALPES", "prix_m2": 3182, "year": 2024,
         "lat": 43.831, "lon": 5.785},
        {"id_mutation": "mt3", "date_mutation": "2024-07-01", "valeur_fonciere": 250_000,
         "type_local": "Maison", "surface": 95, "rooms": 4, "surface_terrain": 200,
         "num": "8", "voie": "AV JEAN GIONO", "prix_m2": 2632, "year": 2024,
         "lat": 43.831, "lon": 5.790},
        {"id_mutation": "mt4", "date_mutation": "2023-09-15", "valeur_fonciere": 290_000,
         "type_local": "Maison", "surface": 105, "rooms": 4, "surface_terrain": 550,
         "num": "3", "voie": "CHEMIN DE LA THOMASSINE", "prix_m2": 2762, "year": 2023,
         "lat": 43.841, "lon": 5.765},
        {"id_mutation": "mt5", "date_mutation": "2024-01-20", "valeur_fonciere": 280_000,
         "type_local": "Maison", "surface": 100, "rooms": 4, "surface_terrain": 480,
         "num": "15", "voie": "RUE DES ALPES", "prix_m2": 2800, "year": 2024,
         "lat": 43.830, "lon": 5.784},
    ]
    with connect() as conn:
        conn.executemany(_INSERT_TERRAIN_SQL, rows)


def _seed_with_outlier(db_path):
    """Seed with normal transactions + one outlier (family sale at 100 €/m²)."""
    from shadow_tester.storage import connect

    rows = [
        {"id_mutation": "mn1", "date_mutation": "2024-03-10", "valeur_fonciere": 270_000,
         "type_local": "Maison", "surface": 100, "rooms": 4, "surface_terrain": None,
         "num": "12", "voie": "RUE DES ALPES", "prix_m2": 2700, "year": 2024,
         "lat": 43.830, "lon": 5.784},
        {"id_mutation": "mn2", "date_mutation": "2024-05-18", "valeur_fonciere": 295_000,
         "type_local": "Maison", "surface": 110, "rooms": 5, "surface_terrain": None,
         "num": "24", "voie": "RUE DES ALPES", "prix_m2": 2682, "year": 2024,
         "lat": 43.831, "lon": 5.785},
        {"id_mutation": "mn3", "date_mutation": "2024-07-01", "valeur_fonciere": 250_000,
         "type_local": "Maison", "surface": 95, "rooms": 4, "surface_terrain": None,
         "num": "8", "voie": "AV JEAN GIONO", "prix_m2": 2632, "year": 2024,
         "lat": 43.831, "lon": 5.790},
        {"id_mutation": "mn4", "date_mutation": "2023-09-15", "valeur_fonciere": 260_000,
         "type_local": "Maison", "surface": 105, "rooms": 4, "surface_terrain": None,
         "num": "3", "voie": "CHEMIN DE LA THOMASSINE", "prix_m2": 2476, "year": 2023,
         "lat": 43.841, "lon": 5.765},
        {"id_mutation": "mn5", "date_mutation": "2024-01-20", "valeur_fonciere": 280_000,
         "type_local": "Maison", "surface": 100, "rooms": 4, "surface_terrain": None,
         "num": "15", "voie": "RUE DES ALPES", "prix_m2": 2800, "year": 2024,
         "lat": 43.830, "lon": 5.784},
        # Outlier: family sale at 10 000€ for a 100m² house → 100 €/m²
        {"id_mutation": "m-outlier", "date_mutation": "2024-02-15", "valeur_fonciere": 10_000,
         "type_local": "Maison", "surface": 100, "rooms": 4, "surface_terrain": None,
         "num": "99", "voie": "RUE DES ALPES", "prix_m2": 100, "year": 2024,
         "lat": 43.830, "lon": 5.784},
    ]
    with connect() as conn:
        conn.executemany(_INSERT_TERRAIN_SQL, rows)


def test_find_comparables_basic(isolated_db):
    from shadow_tester.comps import Target, find_comparables

    _seed(isolated_db)
    target = Target(
        commune="04112",
        type_local="Maison",
        surface=100,
        rooms=4,
        surface_tol=0.25,
        max_years_old=5,
    )
    result = find_comparables(target)

    # m6 is too old (2020, outside 5-year window from 2024) — must be filtered.
    ids = [c.id_mutation for c in result.comps]
    assert "m6" not in ids

    # m4 is 160 m² → outside ±25% of 100 m² (75–125) → filtered.
    assert "m4" not in ids

    # m5 (85 m²) is within tolerance and should be included.
    assert "m5" in ids

    # Appartement rows must never appear.
    assert all(c.type_local == "Maison" for c in result.comps)

    # We have enough comps for a fourchette.
    assert result.n_comps >= 3
    assert result.median_prix_m2 is not None
    assert result.suggested_price_mid is not None

    # Confidence: low if <5, medium if 5-9, high if >=10.
    assert result.confidence in {"low", "medium", "high"}


def test_find_comparables_prefers_nearby_with_address_anchor(isolated_db):
    """With a precise lat/lon anchor, nearby comps should score higher."""
    from shadow_tester.comps import Target, find_comparables

    _seed(isolated_db)
    # Anchor right on rue des Alpes.
    target = Target(
        commune="04112",
        type_local="Maison",
        surface=100,
        rooms=4,
        lat=43.8300,
        lon=5.7846,
        radius_km=2.0,
        surface_tol=0.30,
        max_years_old=5,
    )
    result = find_comparables(target)
    assert result.comps, "expected at least one comp"
    # Top result should be on rue des Alpes (m1 or m2, both 0.0x km away).
    top = result.comps[0]
    assert "ALPES" in top.adresse.upper()
    # Distances are populated.
    assert all(c.distance_km is not None for c in result.comps)


def test_find_comparables_street_keyword_filter(isolated_db):
    """Passing --street keyword hard-filters to that voie."""
    from shadow_tester.comps import Target, find_comparables

    _seed(isolated_db)
    target = Target(
        commune="04112",
        type_local="Maison",
        surface=100,
        rooms=4,
        street_keyword="alpes",
        surface_tol=0.30,
        max_years_old=5,
    )
    result = find_comparables(target)
    assert result.comps
    for c in result.comps:
        assert "ALPES" in c.adresse.upper()


def test_find_comparables_verdict_within_range(isolated_db):
    from shadow_tester.comps import Target, find_comparables

    _seed(isolated_db)
    target = Target(
        commune="04112",
        type_local="Maison",
        surface=100,
        rooms=4,
        budget=270_000,        # close to the median of nearby 100 m² houses
        surface_tol=0.25,
        max_years_old=5,
    )
    result = find_comparables(target)
    assert result.verdict is not None
    # Must classify as "dans" or "en-dessous" or "au-dessus".
    assert any(
        word in result.verdict
        for word in ("dans", "en-dessous", "au-dessus")
    )


def test_find_comparables_verdict_above_range(isolated_db):
    from shadow_tester.comps import Target, find_comparables

    _seed(isolated_db)
    target = Target(
        commune="04112",
        type_local="Maison",
        surface=100,
        rooms=4,
        budget=500_000,        # clearly above the fourchette
        surface_tol=0.25,
        max_years_old=5,
    )
    result = find_comparables(target)
    assert result.verdict is not None
    assert "au-dessus" in result.verdict


def test_find_comparables_respects_limit(isolated_db):
    from shadow_tester.comps import Target, find_comparables

    _seed(isolated_db)
    target = Target(
        commune="04112",
        type_local="Maison",
        surface=100,
        surface_tol=0.50,
        max_years_old=5,
        limit=2,
    )
    result = find_comparables(target)
    assert len(result.comps) <= 2


def test_find_comparables_empty_commune(isolated_db):
    """A commune with no DVF data must return an empty result, not raise."""
    from shadow_tester.comps import Target, find_comparables

    _seed(isolated_db)
    target = Target(commune="99999", type_local="Maison", surface=100)
    result = find_comparables(target)
    assert result.comps == []
    assert result.median_prix_m2 is None


def test_find_comparables_with_terrain(isolated_db):
    """Surface terrain scoring should affect ranking for Maisons."""
    from shadow_tester.comps import Target, find_comparables

    _seed_with_terrain(isolated_db)
    target = Target(
        commune="04112",
        type_local="Maison",
        surface=100,
        surface_terrain=500.0,
        surface_tol=0.30,
        max_years_old=5,
    )
    result = find_comparables(target)
    assert result.comps
    # At least one comp should have terrain_score > 0.
    has_terrain = [c for c in result.comps if c.terrain_score > 0]
    assert has_terrain


def test_outlier_filter_removes_family_sale(isolated_db):
    """A transaction at 100 €/m² (family sale) should be filtered out."""
    from shadow_tester.comps import Target, find_comparables

    _seed_with_outlier(isolated_db)
    target = Target(
        commune="04112",
        type_local="Maison",
        surface=100,
        surface_tol=0.50,
        max_years_old=5,
    )
    result = find_comparables(target)
    ids = [c.id_mutation for c in result.comps]
    # The outlier (m-outlier at 100 €/m²) should be filtered.
    assert "m-outlier" not in ids
    # Normal transactions should remain.
    assert len(result.comps) >= 3
