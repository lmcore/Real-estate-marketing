"""User-maintained property notes — the ground-truth layer for condition.

Everything in this module reflects things the user has *personally* seen:
visits, listings they consulted, their own estimates. These notes always
override any automatic proxy (DPE, listings heuristics, Claude Vision) when
they exist for the same bien.
"""

from shadow_tester.notes.models import (
    ALLOWED_CONDITIONS,
    ALLOWED_SOURCES,
    PropertyNote,
    normalise_condition,
    normalise_source,
)
from shadow_tester.notes.repo import (
    add_note,
    delete_note,
    find_notes_for_mutations,
    get_note,
    list_notes,
    update_note,
)

__all__ = [
    "ALLOWED_CONDITIONS",
    "ALLOWED_SOURCES",
    "PropertyNote",
    "add_note",
    "delete_note",
    "find_notes_for_mutations",
    "get_note",
    "list_notes",
    "normalise_condition",
    "normalise_source",
    "update_note",
]
