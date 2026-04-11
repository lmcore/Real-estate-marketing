"""Download + cache INSEE Dossier Complet files.

INSEE publishes annual releases as ZIP archives (with a CSV inside) at URLs
of the form::

    https://www.insee.fr/fr/statistiques/fichier/<id>/dossier_complet.zip

Because the numeric ID changes every release, the URL is passed explicitly
by the caller. The client caches both the ZIP and the extracted CSV on disk.
"""

from __future__ import annotations

import logging
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from shadow_tester.config import get_settings

logger = logging.getLogger(__name__)


class INSEEDownloadError(RuntimeError):
    """Raised when an INSEE file cannot be downloaded or extracted."""


@dataclass(frozen=True)
class INSEEFile:
    url: str
    zip_path: Path
    csv_path: Path
    millesime: int


class INSEEClient:
    """Minimal HTTP client for INSEE bulk files."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        timeout: float = 180.0,
    ) -> None:
        settings = get_settings()
        self.cache_dir = (cache_dir or settings.cache_dir) / "insee"
        self.timeout = timeout
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _zip_path(self, millesime: int) -> Path:
        return self.cache_dir / f"dossier_complet_{millesime}.zip"

    def _csv_dir(self, millesime: int) -> Path:
        return self.cache_dir / f"dossier_complet_{millesime}"

    def download(
        self,
        url: str,
        millesime: int,
        *,
        force: bool = False,
    ) -> INSEEFile:
        """Download and extract the CSV for ``millesime`` from ``url``."""
        zip_path = self._zip_path(millesime)
        csv_dir = self._csv_dir(millesime)

        if not zip_path.exists() or force:
            logger.info("Downloading INSEE %s", url)
            try:
                with (
                    httpx.Client(timeout=self.timeout, follow_redirects=True) as client,
                    client.stream("GET", url) as response,
                ):
                    response.raise_for_status()
                    tmp = zip_path.with_suffix(".zip.part")
                    with tmp.open("wb") as fh:
                        for chunk in response.iter_bytes(chunk_size=1 << 16):
                            fh.write(chunk)
                    tmp.replace(zip_path)
            except httpx.HTTPError as exc:
                raise INSEEDownloadError(f"Failed to download {url}: {exc}") from exc
            logger.info("Saved INSEE archive to %s (%d bytes)", zip_path, zip_path.stat().st_size)

        # Extract (or re-extract on --force).
        if force and csv_dir.exists():
            shutil.rmtree(csv_dir)
        csv_dir.mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(zip_path) as zf:
                csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not csv_names:
                    raise INSEEDownloadError(f"No CSV file inside {zip_path}")
                # The dossier complet archives usually contain one main CSV.
                # Pick the largest (the detailed per-commune file).
                csv_names.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
                chosen = csv_names[0]
                target = csv_dir / Path(chosen).name
                if not target.exists() or force:
                    with zf.open(chosen) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
        except zipfile.BadZipFile as exc:
            raise INSEEDownloadError(f"{zip_path} is not a valid ZIP file: {exc}") from exc

        return INSEEFile(url=url, zip_path=zip_path, csv_path=target, millesime=millesime)
