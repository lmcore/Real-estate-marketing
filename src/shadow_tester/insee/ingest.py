"""High-level INSEE ingestion: parse → normalise → upsert into SQLite."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from shadow_tester.insee.client import INSEEClient
from shadow_tester.insee.mapping import DEFAULT_MAPPING, INSEEMapping
from shadow_tester.insee.parser import load_insee_csv, normalise_rows
from shadow_tester.storage import connect

logger = logging.getLogger(__name__)


_INSERT_SQL = """
INSERT OR REPLACE INTO insee_commune (
    code_commune, millesime,
    nom_commune, code_departement, code_region,
    population, superficie_km2, densite_hab_km2,
    logements_total, residences_principales, residences_secondaires, logements_vacants,
    taux_vacance, taux_residences_sec, part_proprietaires,
    revenu_median_uc, taux_pauvrete,
    pop_active_1564, taux_chomage_1564,
    source_url
) VALUES (
    :code_commune, :millesime,
    :nom_commune, :code_departement, :code_region,
    :population, :superficie_km2, :densite_hab_km2,
    :logements_total, :residences_principales, :residences_secondaires, :logements_vacants,
    :taux_vacance, :taux_residences_sec, :part_proprietaires,
    :revenu_median_uc, :taux_pauvrete,
    :pop_active_1564, :taux_chomage_1564,
    :source_url
)
"""

_LOG_SQL = """
INSERT OR REPLACE INTO insee_ingest_log (source_url, millesime, rows_loaded)
VALUES (?, ?, ?)
"""

# Columns the INSERT SQL actually reads. Any extra derived field that sneaks
# into the record dict must be stripped before binding.
_PERSISTED_COLUMNS: frozenset[str] = frozenset(
    {
        "code_commune",
        "millesime",
        "nom_commune",
        "code_departement",
        "code_region",
        "population",
        "superficie_km2",
        "densite_hab_km2",
        "logements_total",
        "residences_principales",
        "residences_secondaires",
        "logements_vacants",
        "taux_vacance",
        "taux_residences_sec",
        "part_proprietaires",
        "revenu_median_uc",
        "taux_pauvrete",
        "pop_active_1564",
        "taux_chomage_1564",
        "source_url",
    }
)


@dataclass
class IngestResult:
    millesime: int
    rows_loaded: int
    source_url: str
    communes_filter: tuple[str, ...] | None = None


def _prepare(record: dict[str, object]) -> dict[str, object]:
    """Keep only columns the SQL expects and coerce NumPy / NA to None."""
    out: dict[str, object] = {}
    for col in _PERSISTED_COLUMNS:
        v = record.get(col)
        if v is None:
            out[col] = None
        elif isinstance(v, (int, float, str)):
            out[col] = v
        else:
            # numpy scalar fallback
            try:
                out[col] = float(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                out[col] = str(v)
    return out


def ingest_from_file(
    csv_path: Path,
    *,
    millesime: int,
    communes: Iterable[str] | None = None,
    mapping: INSEEMapping | None = None,
    source_url: str = "",
) -> IngestResult:
    """Parse a local INSEE CSV and load it into SQLite.

    Useful for unit-testing and for running against manually downloaded files.
    """
    raw = load_insee_csv(csv_path, communes=communes)
    records = list(
        normalise_rows(
            raw,
            millesime=millesime,
            mapping=mapping or DEFAULT_MAPPING,
            source_url=source_url,
        )
    )
    prepared = [_prepare(r) for r in records]

    with connect() as conn:
        conn.executemany(_INSERT_SQL, prepared)
        conn.execute(_LOG_SQL, (source_url, millesime, len(prepared)))

    logger.info(
        "Loaded %d INSEE rows (millesime=%d) from %s", len(prepared), millesime, csv_path
    )
    return IngestResult(
        millesime=millesime,
        rows_loaded=len(prepared),
        source_url=source_url,
        communes_filter=tuple(communes) if communes else None,
    )


def ingest_from_url(
    url: str,
    *,
    millesime: int,
    communes: Iterable[str] | None = None,
    mapping: INSEEMapping | None = None,
    force: bool = False,
    client: INSEEClient | None = None,
) -> IngestResult:
    """Download the INSEE archive from ``url`` and ingest it."""
    client = client or INSEEClient()
    insee_file = client.download(url, millesime, force=force)
    return ingest_from_file(
        insee_file.csv_path,
        millesime=millesime,
        communes=communes,
        mapping=mapping,
        source_url=url,
    )
