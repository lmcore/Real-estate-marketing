"""Parse INSEE "Dossier Complet" CSVs and normalise them to our schema.

The raw file is a semi-colon separated CSV (UTF-8 BOM or ISO-8859-15 depending
on the release) with one row per French commune and ~400 indicator columns.
We only keep the subset described by an :class:`INSEEMapping` plus a few
metadata columns, and compute derived indicators (density, vacancy rate, etc.)
before loading into SQLite.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterable, Iterator
from pathlib import Path

from shadow_tester.insee.mapping import DEFAULT_MAPPING, INSEEMapping

logger = logging.getLogger(__name__)

# Numeric columns we persist in insee_commune.
_NUMERIC_FIELDS: tuple[str, ...] = (
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
)


def _detect_encoding(path: Path) -> str:
    """Sniff BOM to pick between UTF-8 and ISO-8859-15.

    INSEE open-data releases use one or the other depending on the vintage.
    """
    with path.open("rb") as fh:
        head = fh.read(4)
    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    # Heuristic: if the rest is ASCII-clean, UTF-8 works too.
    try:
        path.read_text(encoding="utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "iso-8859-15"


def _parse_number(value: str | None) -> float | None:
    """INSEE uses '.' in recent releases but also ',' in older ones."""
    if value is None:
        return None
    v = value.strip()
    if not v or v in {"N/A", "NA", ".", "nd"}:
        return None
    v = v.replace(",", ".").replace("\u202f", "").replace(" ", "")
    try:
        return float(v)
    except ValueError:
        return None


def _first_present(row: dict[str, str], candidates: Iterable[str]) -> float | None:
    for col in candidates:
        if col in row:
            value = _parse_number(row[col])
            if value is not None:
                return value
    return None


def load_insee_csv(
    path: Path,
    *,
    communes: Iterable[str] | None = None,
    delimiter: str = ";",
) -> list[dict[str, str]]:
    """Read a raw INSEE CSV and return a list of row dicts.

    Parameters
    ----------
    path:
        Path to the CSV (not a ZIP — unzip first).
    communes:
        Optional iterable of INSEE commune codes. When provided, only these
        rows are kept — useful to avoid loading 35k rows when you only care
        about one commune.
    """
    encoding = _detect_encoding(path)
    logger.debug("Reading INSEE CSV %s (encoding=%s)", path, encoding)

    wanted: set[str] | None = None
    if communes is not None:
        wanted = {c.zfill(5) for c in communes}

    out: list[dict[str, str]] = []
    with path.open("r", encoding=encoding, newline="") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        if reader.fieldnames is None:
            raise ValueError(f"INSEE CSV {path} has no header row")
        if "CODGEO" not in reader.fieldnames:
            raise ValueError(
                f"INSEE CSV {path} is missing 'CODGEO'. Columns start with: "
                f"{reader.fieldnames[:5]}"
            )
        for row in reader:
            code = (row.get("CODGEO") or "").strip().zfill(5)
            if wanted is not None and code not in wanted:
                continue
            row["CODGEO"] = code
            out.append(row)

    logger.info("Loaded %d INSEE rows from %s", len(out), path)
    return out


def normalise_rows(
    raw_rows: Iterable[dict[str, str]],
    *,
    millesime: int,
    mapping: INSEEMapping | None = None,
    source_url: str | None = None,
) -> Iterator[dict[str, object]]:
    """Turn raw INSEE rows into records ready for :mod:`storage.insee_commune`.

    Derived metrics (density, vacancy %, home-ownership %, unemployment %)
    are computed on the fly when the underlying counters are available.
    """
    resolved = (mapping or DEFAULT_MAPPING).for_year(millesime)

    for row in raw_rows:
        record: dict[str, object] = {
            "code_commune": row.get("CODGEO") or "",
            "nom_commune": row.get("LIBGEO"),
            "code_departement": row.get("DEP"),
            "code_region": row.get("REG"),
            "millesime": millesime,
            "source_url": source_url,
        }

        # Straight numeric fields via the mapping.
        for internal, candidates in resolved.field_map.items():
            record[internal] = _first_present(row, candidates)

        # Superficie (stable column name across releases).
        record["superficie_km2"] = _parse_number(row.get(resolved.superficie_column))

        # Derived: density (hab/km²)
        pop = _num(record.get("population"))
        surf = _num(record.get("superficie_km2"))
        record["densite_hab_km2"] = (
            round(pop / surf, 2) if pop is not None and surf and surf > 0 else None
        )

        # Derived: vacancy rate (%)
        log_total = _num(record.get("logements_total"))
        log_vac = _num(record.get("logements_vacants"))
        record["taux_vacance"] = (
            round(100 * log_vac / log_total, 2)
            if log_total and log_total > 0 and log_vac is not None
            else None
        )

        # Derived: % of secondary residences
        log_rs = _num(record.get("residences_secondaires"))
        record["taux_residences_sec"] = (
            round(100 * log_rs / log_total, 2)
            if log_total and log_total > 0 and log_rs is not None
            else None
        )

        # Derived: % of owner-occupied residences.
        # INSEE publishes either the count (P{yy}_RP_PROP) or already a rate.
        # Here we treat it as a count and divide by RP if both are present,
        # otherwise we fall through.
        rp = _num(record.get("residences_principales"))
        rp_prop = _num(record.pop("part_proprietaires_rp", None))
        record["part_proprietaires"] = (
            round(100 * rp_prop / rp, 2)
            if rp and rp > 0 and rp_prop is not None
            else None
        )

        # Derived: unemployment rate 15-64
        chom = _num(record.pop("chom_1564", None))
        active = _num(record.get("pop_active_1564"))
        record["taux_chomage_1564"] = (
            round(100 * chom / active, 2)
            if active and active > 0 and chom is not None
            else None
        )
        record.pop("pop_1564", None)  # not persisted, used only for derivations later

        # Ensure all persisted numeric fields exist (possibly None).
        for f in _NUMERIC_FIELDS:
            record.setdefault(f, None)

        yield record


def _num(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
