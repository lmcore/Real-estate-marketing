"""High-level ingestion: download → parse → clean → load into SQLite."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from shadow_tester.dvf.client import DVFClient, DVFDownloadError
from shadow_tester.dvf.parser import clean_dataframe, iter_records, load_csv
from shadow_tester.storage import connect

logger = logging.getLogger(__name__)


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
    :date_mutation, :nature_mutation, :valeur_fonciere,
    :code_postal, :code_commune, :nom_commune, :code_departement,
    :type_local, :surface_reelle_bati, :nombre_pieces_principales, :surface_terrain,
    :adresse_numero, :adresse_nom_voie, :id_parcelle,
    :longitude, :latitude,
    :prix_m2, :year
)
"""

_LOG_INSERT_SQL = """
INSERT OR REPLACE INTO dvf_ingest_log (code_commune, year, rows_loaded, source_url)
VALUES (?, ?, ?, ?)
"""


@dataclass
class IngestResult:
    commune: str
    year: int
    rows_loaded: int
    source_url: str
    skipped: bool = False
    error: str | None = None


def ingest_commune_years(
    commune: str,
    years: Iterable[int],
    *,
    force: bool = False,
    client: DVFClient | None = None,
) -> list[IngestResult]:
    """Ingest DVF transactions for ``commune`` over the given ``years``.

    Idempotent: rows are upserted by composite key, and the ``dvf_ingest_log``
    table records what has been loaded. Pass ``force=True`` to re-download
    cached CSVs from the network.
    """
    client = client or DVFClient()
    results: list[IngestResult] = []

    for year in years:
        try:
            dvf_file = client.download(commune, year, force=force)
        except DVFDownloadError as exc:
            logger.warning("Skipping %s/%s: %s", commune, year, exc)
            results.append(
                IngestResult(
                    commune=commune,
                    year=year,
                    rows_loaded=0,
                    source_url=client.build_url(commune, year),
                    skipped=True,
                    error=str(exc),
                )
            )
            continue

        logger.info("Parsing %s", dvf_file.path)
        df = load_csv(dvf_file.path)
        cleaned = clean_dataframe(df)

        # Defensive: only keep rows matching the requested commune (a CSV should
        # already contain a single commune, but be strict about it).
        cleaned = cleaned[cleaned["code_commune"] == commune]

        records = list(iter_records(cleaned))
        with connect() as conn:
            conn.executemany(_INSERT_SQL, records)
            conn.execute(_LOG_INSERT_SQL, (commune, year, len(records), dvf_file.url))

        logger.info("Loaded %d rows for %s/%s", len(records), commune, year)
        results.append(
            IngestResult(
                commune=commune,
                year=year,
                rows_loaded=len(records),
                source_url=dvf_file.url,
            )
        )

    return results
