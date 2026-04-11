"""End-to-end test: parse the fixture → load into a temp SQLite → compute stats."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "sample_dvf_04112.csv"


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point the settings at a temp dir so the real DB is never touched."""
    db_path = tmp_path / "test.sqlite"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    # Reset the cached settings singleton and environment.
    from shadow_tester import config as cfg

    monkeypatch.setenv("SHADOW_DB_PATH", str(db_path))
    monkeypatch.setenv("SHADOW_CACHE_DIR", str(cache_dir))
    cfg._settings = None  # force reload
    yield db_path
    cfg._settings = None


def test_end_to_end_ingest_and_stats(isolated_db):
    from shadow_tester.dvf.ingest import _INSERT_SQL
    from shadow_tester.dvf.parser import clean_dataframe, iter_records, load_csv
    from shadow_tester.dvf.stats import compute_commune_stats
    from shadow_tester.storage import connect

    # Manually run the parse → load step (no network).
    cleaned = clean_dataframe(load_csv(SAMPLE))
    records = list(iter_records(cleaned))

    with connect() as conn:
        conn.executemany(_INSERT_SQL, records)

    stats = compute_commune_stats("04112")
    assert stats.total_transactions > 0

    # We expect both Maison and Appartement buckets for 2023.
    types = {b.type_local for b in stats.buckets}
    assert types == {"Maison", "Appartement"}

    # Sanity check: Maison 2023 median between 2000 and 4000 €/m² (fixture values).
    maison = next(b for b in stats.buckets if b.type_local == "Maison" and b.year == 2023)
    assert maison.n_transactions == 3
    assert 2000 <= maison.median_prix_m2 <= 4000

    # Filter by type_local.
    appt_only = compute_commune_stats("04112", type_local="Appartement")
    assert all(b.type_local == "Appartement" for b in appt_only.buckets)
