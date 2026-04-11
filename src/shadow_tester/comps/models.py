"""Dataclasses describing a comparable-search target and its results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Target:
    """The bien the user wants to compare against DVF transactions.

    Only ``commune``, ``type_local`` and ``surface`` are required. The
    geographic anchor is optional — when present it is used to rank comps
    by distance.

    Exactly one of ``address`` / (``lat``, ``lon``) / ``street_keyword`` may
    be provided, or none (commune-wide search).
    """

    commune: str
    type_local: str                     # "Maison" or "Appartement"
    surface: float

    rooms: int | None = None
    budget: float | None = None          # target price in EUR (for the verdict)

    address: str | None = None           # "12 rue des Alpes, 04100 Manosque"
    lat: float | None = None
    lon: float | None = None
    street_keyword: str | None = None    # substring match on adresse_nom_voie

    # Tuning knobs (sensible defaults)
    surface_tol: float = 0.25            # ±25 % window on surface
    rooms_tol: int = 1                   # ±1 piece window
    radius_km: float = 5.0               # used for distance scoring
    max_years_old: int = 5               # reject older transactions
    limit: int = 10

    def __post_init__(self) -> None:
        self.commune = self.commune.zfill(5)
        if self.type_local not in {"Maison", "Appartement"}:
            raise ValueError(
                f"Unsupported type_local {self.type_local!r} (expected Maison or Appartement)"
            )
        if self.surface <= 0:
            raise ValueError(f"Surface must be positive, got {self.surface}")
        if self.surface_tol <= 0 or self.surface_tol > 1.0:
            raise ValueError(f"surface_tol must be in (0, 1], got {self.surface_tol}")

    @property
    def surface_min(self) -> float:
        return self.surface * (1.0 - self.surface_tol)

    @property
    def surface_max(self) -> float:
        return self.surface * (1.0 + self.surface_tol)

    @property
    def has_anchor(self) -> bool:
        return (self.lat is not None and self.lon is not None) or bool(self.street_keyword)


@dataclass
class Comp:
    """A single DVF transaction returned as a comparable."""

    id_mutation: str
    date_mutation: str
    year: int
    type_local: str
    surface: float
    rooms: int | None
    valeur_fonciere: float
    prix_m2: float | None
    adresse: str
    lat: float | None
    lon: float | None

    # Derived
    distance_km: float | None = None
    surface_score: float = 0.0
    distance_score: float = 0.0
    recency_score: float = 0.0
    rooms_score: float = 0.0
    total_score: float = 0.0


@dataclass
class CompResult:
    """Aggregate result of a comparable search."""

    target: Target
    comps: list[Comp] = field(default_factory=list)

    # Aggregates over the returned comps (not the full unranked set).
    n_comps: int = 0
    median_prix_m2: float | None = None
    p25_prix_m2: float | None = None
    p75_prix_m2: float | None = None
    suggested_price_low: float | None = None     # P25 * surface target
    suggested_price_mid: float | None = None     # median * surface target
    suggested_price_high: float | None = None    # P75 * surface target

    # Qualitative verdict when target.budget is set.
    verdict: str | None = None

    # Confidence band: low / medium / high depending on the number of comps.
    confidence: str = "low"
