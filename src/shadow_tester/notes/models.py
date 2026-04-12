"""Dataclasses and validation for user-maintained property notes."""

from __future__ import annotations

from dataclasses import dataclass

# Condition buckets — ordered from worst to best. These are also the values
# any automatic proxy (DPE mapping, listings heuristics, Vision) must emit,
# so that notes and proxies compare on equal terms.
ALLOWED_CONDITIONS: tuple[str, ...] = (
    "brut",         # gros œuvre uniquement, absolument tout à faire
    "a_renover",    # travaux lourds à prévoir
    "partiel",      # rafraîchissement / rénovation partielle
    "renove",       # refait à neuf ou récemment rénové
    "inconnu",      # explicitly unknown
)

# How the user obtained the information. Kept deliberately short so it is
# self-explanatory when reading back old notes.
ALLOWED_SOURCES: tuple[str, ...] = (
    "visite",       # user physically visited the bien
    "annonce",      # user consulted a listing (LBC, SeLoger, PAP, notaire, …)
    "estimation",   # user's own gut estimate (e.g. from a drive-by)
    "autre",        # anything else (word of mouth, agent, …)
)

# Common aliases to make the CLI forgiving.
_CONDITION_ALIASES: dict[str, str] = {
    "raw": "brut",
    "gros-oeuvre": "brut",
    "gros_oeuvre": "brut",
    "gros-œuvre": "brut",
    "a-renover": "a_renover",
    "à_rénover": "a_renover",
    "a renover": "a_renover",
    "a rénover": "a_renover",
    "à renover": "a_renover",
    "à rénover": "a_renover",
    "rénover": "a_renover",
    "travaux": "a_renover",
    "partial": "partiel",
    "partiellement": "partiel",
    "partiellement-renove": "partiel",
    "rafraichissement": "partiel",
    "rafraîchissement": "partiel",
    "rénové": "renove",
    "refait": "renove",
    "neuf": "renove",
    "unknown": "inconnu",
    "?": "inconnu",
    "": "inconnu",
}

_SOURCE_ALIASES: dict[str, str] = {
    "visit": "visite",
    "listing": "annonce",
    "lbc": "annonce",
    "leboncoin": "annonce",
    "seloger": "annonce",
    "pap": "annonce",
    "estimate": "estimation",
    "other": "autre",
}


def normalise_condition(raw: str) -> str:
    """Return a canonical condition string or raise ``ValueError``."""
    if raw is None:
        raise ValueError("condition is required")
    key = raw.strip().lower().replace("-", "_")
    if key in _CONDITION_ALIASES:
        key = _CONDITION_ALIASES[key]
    # Try the non-underscore variant too (aliases above are mixed).
    if key not in ALLOWED_CONDITIONS:
        alt = key.replace("_", " ")
        if alt in _CONDITION_ALIASES:
            key = _CONDITION_ALIASES[alt]
    if key not in ALLOWED_CONDITIONS:
        raise ValueError(
            f"Unknown condition {raw!r}. Expected one of {', '.join(ALLOWED_CONDITIONS)}."
        )
    return key


def normalise_source(raw: str) -> str:
    """Return a canonical source string or raise ``ValueError``."""
    if raw is None:
        raise ValueError("source is required")
    key = raw.strip().lower()
    if key in _SOURCE_ALIASES:
        key = _SOURCE_ALIASES[key]
    if key not in ALLOWED_SOURCES:
        raise ValueError(
            f"Unknown source {raw!r}. Expected one of {', '.join(ALLOWED_SOURCES)}."
        )
    return key


@dataclass
class PropertyNote:
    """One piece of ground-truth information about a bien.

    At least one of ``id_mutation`` or ``adresse`` must be provided — a note
    that anchors to neither would be un-joinable with the rest of the system.
    """

    condition: str
    source: str

    # Optional anchors (at least one required)
    id_mutation: str | None = None
    adresse: str | None = None
    commune: str | None = None
    lat: float | None = None
    lon: float | None = None

    # Optional quantitative payload
    travaux_estime: float | None = None
    prix_annonce: float | None = None
    note: str | None = None

    # Populated by the repo layer
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        self.condition = normalise_condition(self.condition)
        self.source = normalise_source(self.source)

        if self.commune is not None:
            self.commune = self.commune.zfill(5)

        if not self.id_mutation and not self.adresse:
            raise ValueError(
                "PropertyNote requires at least one of id_mutation or adresse "
                "to be joinable to the rest of the system."
            )

        if self.travaux_estime is not None and self.travaux_estime < 0:
            raise ValueError(
                f"travaux_estime must be >= 0, got {self.travaux_estime}"
            )
        if self.prix_annonce is not None and self.prix_annonce <= 0:
            raise ValueError(
                f"prix_annonce must be > 0, got {self.prix_annonce}"
            )
