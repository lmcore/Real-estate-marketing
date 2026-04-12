"""SQLite CRUD for the ``listings`` table."""

from __future__ import annotations

import logging
import sqlite3

from shadow_tester.listings.models import Listing
from shadow_tester.storage import connect

logger = logging.getLogger(__name__)

_ALL_COLS = (
    "source", "url", "title", "description",
    "price_asked", "surface", "rooms", "type_local",
    "commune", "adresse_approx", "lat", "lon",
    "condition", "condition_source", "condition_confidence", "condition_rationale",
    "first_seen", "last_seen", "disappeared_at",
    "matched_mutation_id", "match_score",
    "raw_html", "notes",
)


def _row_to_listing(row: sqlite3.Row) -> Listing:
    listing = Listing(
        source=row["source"],
        url=row["url"],
        title=row["title"],
        description=row["description"],
        price_asked=row["price_asked"],
        surface=row["surface"],
        rooms=int(row["rooms"]) if row["rooms"] is not None else None,
        type_local=row["type_local"],
        commune=row["commune"],
        adresse_approx=row["adresse_approx"],
        lat=row["lat"],
        lon=row["lon"],
        condition=row["condition"],
        condition_source=row["condition_source"],
        condition_confidence=row["condition_confidence"],
        condition_rationale=row["condition_rationale"],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        disappeared_at=row["disappeared_at"],
        matched_mutation_id=row["matched_mutation_id"],
        match_score=row["match_score"],
        raw_html=row["raw_html"],
        notes=row["notes"],
    )
    listing.id = int(row["id"])
    listing.created_at = row["created_at"]
    listing.updated_at = row["updated_at"]
    return listing


def add_listing(listing: Listing) -> Listing:
    """Insert and return the listing with populated id/timestamps."""
    placeholders = ", ".join(f":{col}" for col in _ALL_COLS)
    cols = ", ".join(_ALL_COLS)
    sql = f"INSERT INTO listings ({cols}) VALUES ({placeholders})"

    params = {col: getattr(listing, col) for col in _ALL_COLS}

    with connect() as conn:
        cur = conn.execute(sql, params)
        new_id = int(cur.lastrowid)
        row = conn.execute("SELECT * FROM listings WHERE id = ?", (new_id,)).fetchone()

    logger.info(
        "Added listing #%d (%s, %s)",
        new_id,
        listing.source or "unknown",
        listing.type_local or "?",
    )
    return _row_to_listing(row)


def get_listing(listing_id: int) -> Listing | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    return _row_to_listing(row) if row else None


def list_listings(
    *,
    commune: str | None = None,
    condition: str | None = None,
    source: str | None = None,
    matched_only: bool = False,
    unmatched_only: bool = False,
    limit: int = 100,
) -> list[Listing]:
    where: list[str] = []
    params: list[object] = []

    if commune:
        where.append("commune = ?")
        params.append(commune.zfill(5))
    if condition:
        where.append("condition = ?")
        params.append(condition)
    if source:
        where.append("source = ?")
        params.append(source)
    if matched_only:
        where.append("matched_mutation_id IS NOT NULL")
    if unmatched_only:
        where.append("matched_mutation_id IS NULL")

    sql = "SELECT * FROM listings"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY datetime(updated_at) DESC LIMIT ?"
    params.append(int(limit))

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_listing(r) for r in rows]


def delete_listing(listing_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
        return cur.rowcount > 0


def update_listing(listing_id: int, **fields: object) -> Listing | None:
    allowed = set(_ALL_COLS)
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_listing(listing_id)

    assignments = ", ".join(f"{col} = :{col}" for col in updates)
    sql = (
        f"UPDATE listings SET {assignments}, "
        f"updated_at = datetime('now') WHERE id = :id"
    )
    params = dict(updates)
    params["id"] = listing_id

    with connect() as conn:
        cur = conn.execute(sql, params)
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    return _row_to_listing(row) if row else None


def find_listings_for_commune(
    commune: str,
    *,
    type_local: str | None = None,
    unmatched_only: bool = False,
) -> list[Listing]:
    """Return all listings for a commune, optionally filtered."""
    where = ["commune = ?"]
    params: list[object] = [commune.zfill(5)]
    if type_local:
        where.append("type_local = ?")
        params.append(type_local)
    if unmatched_only:
        where.append("matched_mutation_id IS NULL")
    sql = "SELECT * FROM listings WHERE " + " AND ".join(where)
    sql += " ORDER BY datetime(first_seen) DESC"

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_listing(r) for r in rows]
