"""DVF (Demandes de Valeurs Foncières) ingestion and analysis."""

from shadow_tester.dvf.client import DVFClient, DVFDownloadError
from shadow_tester.dvf.ingest import ingest_commune_years
from shadow_tester.dvf.parser import clean_dataframe, load_csv
from shadow_tester.dvf.stats import CommuneStats, compute_commune_stats

__all__ = [
    "CommuneStats",
    "DVFClient",
    "DVFDownloadError",
    "clean_dataframe",
    "compute_commune_stats",
    "ingest_commune_years",
    "load_csv",
]
