"""Parse and clean raw DVF geo-CSV files.

The Etalab geo-DVF schema contains ~40 columns; we only keep those useful for
our demand analysis and normalise a few fields (dates, numeric types, price/m²).

Important caveats about DVF:

* A single "mutation" (transaction) can span several CSV rows — one per
  parcel or per lot. Summing ``valeur_fonciere`` on all rows would therefore
  *double-count* the price. We preserve one row per (id_mutation, disposition,
  parcel) and compute ``prix_m2`` only on rows that represent a single
  built local (``type_local`` in {Maison, Appartement}) with a non-null
  built surface.
* Rows without ``type_local`` (e.g. bare land) keep ``prix_m2 = NULL``.
* Prices use comma as decimal separator in the raw file.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Columns we care about. Matches Etalab's geo-DVF latest schema.
KEEP_COLUMNS: tuple[str, ...] = (
    "id_mutation",
    "date_mutation",
    "numero_disposition",
    "nature_mutation",
    "valeur_fonciere",
    "adresse_numero",
    "adresse_nom_voie",
    "code_postal",
    "code_commune",
    "nom_commune",
    "code_departement",
    "id_parcelle",
    "type_local",
    "surface_reelle_bati",
    "nombre_pieces_principales",
    "surface_terrain",
    "longitude",
    "latitude",
)

NUMERIC_COLUMNS: tuple[str, ...] = (
    "valeur_fonciere",
    "surface_reelle_bati",
    "nombre_pieces_principales",
    "surface_terrain",
    "longitude",
    "latitude",
)

# DVF values we treat as "a real built local" for price/m² calculations.
BUILT_LOCAL_TYPES: frozenset[str] = frozenset({"Maison", "Appartement"})


def load_csv(path: Path) -> pd.DataFrame:
    """Load a raw DVF CSV from disk as a DataFrame, keeping only useful columns."""
    # Use dtype=str by default to control coercion ourselves — DVF uses "," as
    # the decimal separator, so pandas' automatic numeric inference is wrong.
    df = pd.read_csv(
        path,
        dtype=str,
        low_memory=False,
        na_values=["", "NA", "N/A"],
        keep_default_na=True,
    )

    missing = [c for c in KEEP_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"DVF file {path} is missing expected columns: {missing}. "
            "The upstream schema may have changed."
        )

    return df[list(KEEP_COLUMNS)].copy()


def _coerce_numeric(series: pd.Series) -> pd.Series:
    # DVF uses comma as decimal separator: "123456,78"
    cleaned = series.astype("string").str.replace(",", ".", regex=False)
    return pd.to_numeric(cleaned, errors="coerce")


def clean_dataframe(df: pd.DataFrame, *, only_sales: bool = True) -> pd.DataFrame:
    """Normalise a raw DVF DataFrame.

    Parameters
    ----------
    df:
        The DataFrame returned by :func:`load_csv`.
    only_sales:
        Keep only "Vente" and "Vente en l'état futur d'achèvement" rows.
        Adjudications, échanges and expropriations are excluded because they
        are not comparable to a standard retail transaction.
    """
    out = df.copy()

    # Numeric coercion.
    for col in NUMERIC_COLUMNS:
        out[col] = _coerce_numeric(out[col])

    # Disposition as integer with a safe default.
    out["disposition"] = pd.to_numeric(out["numero_disposition"], errors="coerce").fillna(1).astype(int)
    out = out.drop(columns=["numero_disposition"])

    # Dates → ISO strings (keep as text for SQLite friendliness).
    dates = pd.to_datetime(out["date_mutation"], errors="coerce", format="%Y-%m-%d")
    out["date_mutation"] = dates.dt.strftime("%Y-%m-%d")
    out["year"] = dates.dt.year.astype("Int64")

    # Commune code must stay a zero-padded 5-char string (e.g. "04112").
    out["code_commune"] = out["code_commune"].astype("string").str.zfill(5)
    out["code_postal"] = out["code_postal"].astype("string")

    if only_sales:
        keep_nature = {"Vente", "Vente en l'état futur d'achèvement"}
        out = out[out["nature_mutation"].isin(keep_nature)]

    # Drop rows with no valeur_fonciere or no date (unusable).
    out = out.dropna(subset=["valeur_fonciere", "date_mutation"])

    # Compute prix_m2 only for single-local built rows with a positive surface.
    # To avoid double-counting, we also deduplicate on (id_mutation, disposition)
    # when the same mutation has several rows — we keep the row with the largest
    # built surface which is the most representative.
    out = out.sort_values(
        by=["id_mutation", "disposition", "surface_reelle_bati"],
        ascending=[True, True, False],
        na_position="last",
    )

    prix_m2 = pd.Series(pd.NA, index=out.index, dtype="Float64")
    mask = (
        out["type_local"].isin(BUILT_LOCAL_TYPES)
        & out["surface_reelle_bati"].fillna(0).gt(0)
        & out["valeur_fonciere"].fillna(0).gt(0)
    )
    prix_m2.loc[mask] = (
        out.loc[mask, "valeur_fonciere"] / out.loc[mask, "surface_reelle_bati"]
    ).round(2)
    out["prix_m2"] = prix_m2

    # Row index within a mutation: stable ordering for the composite primary key.
    out["row_idx"] = out.groupby(["id_mutation", "disposition"]).cumcount()

    logger.debug("Cleaned DVF frame: %d rows", len(out))
    return out.reset_index(drop=True)


_INT_COLUMNS = {"disposition", "row_idx", "nombre_pieces_principales", "year"}
_FLOAT_COLUMNS = {
    "valeur_fonciere",
    "surface_reelle_bati",
    "surface_terrain",
    "longitude",
    "latitude",
    "prix_m2",
}


def _to_native(col: str, value: object) -> object:
    """Convert pandas / numpy scalars to native Python types sqlite3 understands."""
    if value is None or pd.isna(value):
        return None
    if col in _INT_COLUMNS:
        return int(value)  # handles numpy.int64, pandas Int64
    if col in _FLOAT_COLUMNS:
        return float(value)
    return str(value)


def iter_records(df: pd.DataFrame) -> Iterable[dict]:
    """Yield dicts ready to be inserted in the ``dvf_transactions`` table."""
    columns = [
        "id_mutation",
        "disposition",
        "row_idx",
        "date_mutation",
        "nature_mutation",
        "valeur_fonciere",
        "code_postal",
        "code_commune",
        "nom_commune",
        "code_departement",
        "type_local",
        "surface_reelle_bati",
        "nombre_pieces_principales",
        "surface_terrain",
        "adresse_numero",
        "adresse_nom_voie",
        "id_parcelle",
        "longitude",
        "latitude",
        "prix_m2",
        "year",
    ]
    for row in df[columns].itertuples(index=False, name=None):
        yield {col: _to_native(col, val) for col, val in zip(columns, row, strict=True)}
