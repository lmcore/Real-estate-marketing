"""SQLite CRUD for ``property_notes``.

Thin layer: every function opens its own connection via ``storage.connect``
so callers don't have to manage transactions.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable

from shadow_tester.notes.models import PropertyNote
from shadow_tester.storage import connect

logger = logging.getLogger(__name__)


def _row_to_note(row: sqlite3.Row) -> PropertyNote:
    note = PropertyNote(
        condition=row["condition"],
        source=row["source"],
        id_mutation=row["id_mutation"],
        adresse=row["adresse"],
        commune=row["commune"],
        lat=row["lat"],
        lon=row["lon"],
        travaux_estime=row["travaux_estime"],
        prix_annonce=row["prix_annonce"],
        note=row["note"],
    )
    note.id = int(row["id"])
    note.created_at = row["created_at"]
    note.updated_at = row["updated_at"]
    return note


def add_note(note: PropertyNote) -> PropertyNote:
    """Insert ``note`` and return it populated with id / timestamps."""
    sql = """
    INSERT INTO property_notes (
        id_mutation, adresse, commune, lat, lon,
        condition, source, travaux_estime, prix_annonce, note
    ) VALUES (
        :id_mutation, :adresse, :commune, :lat, :lon,
        :condition, :source, :travaux_estime, :prix_annonce, :note
    )
    """
    params = {
        "id_mutation": note.id_mutation,
        "adresse": note.adresse,
        "commune": note.commune,
        "lat": note.lat,
        "lon": note.lon,
        "condition": note.condition,
        "source": note.source,
        "travaux_estime": note.travaux_estime,
        "prix_annonce": note.prix_annonce,
        "note": note.note,
    }
    with connect() as conn:
        cur = conn.execute(sql, params)
        new_id = int(cur.lastrowid)
        row = conn.execute(
            "SELECT * FROM property_notes WHERE id = ?", (new_id,)
        ).fetchone()
    logger.info("Added property_note #%d (%s)", new_id, note.condition)
    return _row_to_note(row)


def get_note(note_id: int) -> PropertyNote | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM property_notes WHERE id = ?", (note_id,)
        ).fetchone()
    return _row_to_note(row) if row else None


def list_notes(
    *,
    commune: str | None = None,
    condition: str | None = None,
    limit: int = 100,
) -> list[PropertyNote]:
    """Return notes ordered by most recently updated first."""
    where: list[str] = []
    params: list[object] = []
    if commune:
        where.append("commune = ?")
        params.append(commune.zfill(5))
    if condition:
        where.append("condition = ?")
        params.append(condition)

    sql = "SELECT * FROM property_notes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY datetime(updated_at) DESC LIMIT ?"
    params.append(int(limit))

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_note(r) for r in rows]


def delete_note(note_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM property_notes WHERE id = ?", (note_id,))
        return cur.rowcount > 0


def update_note(note_id: int, **fields: object) -> PropertyNote | None:
    """Partial update. Only the columns passed as kwargs are touched."""
    allowed = {
        "id_mutation",
        "adresse",
        "commune",
        "lat",
        "lon",
        "condition",
        "source",
        "travaux_estime",
        "prix_annonce",
        "note",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_note(note_id)

    assignments = ", ".join(f"{col} = :{col}" for col in updates)
    sql = (
        f"UPDATE property_notes SET {assignments}, "
        f"updated_at = datetime('now') WHERE id = :id"
    )
    params = dict(updates)
    params["id"] = note_id

    with connect() as conn:
        cur = conn.execute(sql, params)
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM property_notes WHERE id = ?", (note_id,)
        ).fetchone()
    return _row_to_note(row) if row else None


def find_notes_for_mutations(
    mutation_ids: Iterable[str],
) -> dict[str, PropertyNote]:
    """Return a ``{id_mutation: most_recent_note}`` map.

    When several notes exist for the same mutation, the most recently updated
    one wins — that is the user's latest understanding.
    """
    ids = [m for m in mutation_ids if m]
    if not ids:
        return {}

    placeholders = ",".join("?" * len(ids))
    sql = f"""
    SELECT * FROM property_notes
    WHERE id_mutation IN ({placeholders})
    ORDER BY datetime(updated_at) DESC, id DESC
    """
    with connect() as conn:
        rows = conn.execute(sql, ids).fetchall()

    out: dict[str, PropertyNote] = {}
    for row in rows:
        mid = row["id_mutation"]
        if mid and mid not in out:
            out[mid] = _row_to_note(row)
    return out
