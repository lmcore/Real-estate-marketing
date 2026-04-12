"""Dataclass for user-captured real-estate listings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from shadow_tester.notes.models import normalise_condition


@dataclass
class Listing:
    """A listing the user has manually captured (LBC, SeLoger, PAP, etc.).

    At minimum ``price_asked`` or ``description`` should be provided to be
    useful. ``commune`` is highly recommended for DVF matching later.
    """

    # Source
    source: str | None = None          # leboncoin / seloger / pap / autre
    url: str | None = None
    title: str | None = None
    description: str | None = None

    # Structured
    price_asked: float | None = None
    surface: float | None = None
    rooms: int | None = None
    type_local: str | None = None      # Maison / Appartement

    # Location
    commune: str | None = None
    adresse_approx: str | None = None
    lat: float | None = None
    lon: float | None = None

    # Condition
    condition: str | None = None
    condition_source: str | None = None      # manual / keywords / vision
    condition_confidence: float | None = None
    condition_rationale: str | None = None

    # Temporal
    first_seen: str | None = None
    last_seen: str | None = None
    disappeared_at: str | None = None

    # DVF matching
    matched_mutation_id: str | None = None
    match_score: float | None = None

    # Archive
    raw_html: str | None = None

    notes: str | None = None

    # Populated by repo
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        if self.commune is not None:
            self.commune = self.commune.zfill(5)

        if self.type_local is not None and self.type_local not in {
            "Maison", "Appartement",
        }:
            raise ValueError(
                f"Unsupported type_local {self.type_local!r} "
                "(expected Maison or Appartement)"
            )

        if self.condition is not None:
            self.condition = normalise_condition(self.condition)

        if self.price_asked is not None and self.price_asked <= 0:
            raise ValueError(
                f"price_asked must be > 0, got {self.price_asked}"
            )

        if self.first_seen is None:
            self.first_seen = date.today().isoformat()
        if self.last_seen is None:
            self.last_seen = self.first_seen
