"""INSEE commune-level indicators ingestion and analysis.

Uses the "Dossier Complet" dataset published by INSEE, which aggregates
~400 indicators (demography, housing, income, employment) per French commune
in a single CSV.

Docs & source:
    https://www.insee.fr/fr/statistiques/2011101
"""

from shadow_tester.insee.client import INSEEClient, INSEEDownloadError
from shadow_tester.insee.indicators import (
    CommuneSummary,
    affordability_ratio,
    load_commune,
    summarize_commune,
)
from shadow_tester.insee.ingest import ingest_from_file, ingest_from_url
from shadow_tester.insee.mapping import DEFAULT_MAPPING, INSEEMapping
from shadow_tester.insee.parser import load_insee_csv, normalise_rows

__all__ = [
    "DEFAULT_MAPPING",
    "CommuneSummary",
    "INSEEClient",
    "INSEEDownloadError",
    "INSEEMapping",
    "affordability_ratio",
    "ingest_from_file",
    "ingest_from_url",
    "load_commune",
    "load_insee_csv",
    "normalise_rows",
    "summarize_commune",
]
