"""Download DVF CSVs from Etalab's geo-dvf public mirror.

The Etalab geo-DVF dataset is published per year and per commune as CSV files at:

    {base}/{year}/communes/{dep}/{insee_code}.csv

Example for Manosque (04112), year 2023:
    https://files.data.gouv.fr/geo-dvf/latest/csv/2023/communes/04/04112.csv

Files are cached on disk so repeated runs don't hit the network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from shadow_tester.config import get_settings

logger = logging.getLogger(__name__)


class DVFDownloadError(RuntimeError):
    """Raised when a DVF CSV cannot be downloaded."""


@dataclass(frozen=True)
class DVFFile:
    commune: str
    year: int
    url: str
    path: Path

    @property
    def departement(self) -> str:
        # INSEE commune codes: first 2 chars for metro, 3 for DOM (97x, 98x).
        return _departement_from_commune(self.commune)


def _departement_from_commune(commune: str) -> str:
    if not commune or len(commune) < 3:
        raise ValueError(f"Invalid commune code: {commune!r}")
    if commune.startswith(("97", "98")):
        return commune[:3]
    return commune[:2]


class DVFClient:
    """Minimal HTTP client for Etalab's geo-DVF CSVs."""

    def __init__(
        self,
        base_url: str | None = None,
        cache_dir: Path | None = None,
        timeout: float = 60.0,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.dvf_base_url).rstrip("/")
        self.cache_dir = cache_dir or settings.cache_dir
        self.timeout = timeout
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def build_url(self, commune: str, year: int) -> str:
        dep = _departement_from_commune(commune)
        return f"{self.base_url}/{year}/communes/{dep}/{commune}.csv"

    def cache_path(self, commune: str, year: int) -> Path:
        return self.cache_dir / f"dvf_{commune}_{year}.csv"

    def download(self, commune: str, year: int, *, force: bool = False) -> DVFFile:
        """Download the CSV for ``commune`` and ``year``, returning its local path.

        Uses the cached file on disk unless ``force=True``.
        Raises :class:`DVFDownloadError` on network / HTTP failure.
        """
        url = self.build_url(commune, year)
        path = self.cache_path(commune, year)

        if path.exists() and not force:
            logger.info("Using cached DVF file %s", path)
            return DVFFile(commune=commune, year=year, url=url, path=path)

        logger.info("Downloading DVF %s", url)
        try:
            with (
                httpx.Client(timeout=self.timeout, follow_redirects=True) as client,
                client.stream("GET", url) as response,
            ):
                if response.status_code == 404:
                    raise DVFDownloadError(
                        f"No DVF data for commune {commune} in {year} "
                        f"(HTTP 404: {url}). It may be too recent "
                        f"or the commune had no transactions."
                    )
                response.raise_for_status()
                tmp = path.with_suffix(".csv.part")
                with tmp.open("wb") as fh:
                    for chunk in response.iter_bytes(chunk_size=65536):
                        fh.write(chunk)
                tmp.replace(path)
        except httpx.HTTPError as exc:
            raise DVFDownloadError(f"Failed to download {url}: {exc}") from exc

        logger.info("Saved DVF file to %s (%d bytes)", path, path.stat().st_size)
        return DVFFile(commune=commune, year=year, url=url, path=path)
