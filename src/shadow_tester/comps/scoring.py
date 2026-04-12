"""Geometry + scoring helpers for the comps engine.

All subscores are in [0, 1] where 1 = perfect match.
"""

from __future__ import annotations

import math

from shadow_tester.comps.models import Comp, Target

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two (lat, lon) points."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))
    return EARTH_RADIUS_KM * c


# ── Scoring weights ──────────────────────────────────────────────────────
# Default weights (no terrain target): surface 35% + distance 30% + récence 20% + pièces 15%.
# When a terrain target is set (Maison only): terrain takes 15%, distance drops to 20%,
# surface drops to 30%. This reflects market reality where lot size has a
# massive impact on Maison price (a 100m² house on 200m² vs 1500m² is not
# the same product).

_W_SURFACE = 0.35
_W_DISTANCE = 0.30
_W_RECENCY = 0.20
_W_ROOMS = 0.15

# Weights when terrain scoring is active (Maison + target.surface_terrain set).
_W_SURFACE_T = 0.30
_W_DISTANCE_T = 0.20
_W_RECENCY_T = 0.15
_W_ROOMS_T = 0.10
_W_TERRAIN = 0.25  # lot size gets a very significant weight

# Tolerance for terrain matching: ±50% (lots vary a lot more than habitable surface).
_TERRAIN_TOL = 0.50


def _surface_score(target_surface: float, comp_surface: float | None) -> float:
    if comp_surface is None or comp_surface <= 0:
        return 0.0
    err = abs(comp_surface - target_surface) / target_surface
    return max(0.0, 1.0 - err)


def _distance_score(
    target: Target,
    comp_lat: float | None,
    comp_lon: float | None,
) -> tuple[float, float | None]:
    """Return (score, distance_km).

    - If the target has lat/lon and the comp has lat/lon, linear falloff from
      1.0 at 0 km down to 0.0 at ``target.radius_km``.
    - If the target has no coordinates, score is 1.0 for everyone (distance
      is unavailable so it shouldn't penalise).
    - If the target has coordinates but the comp doesn't, score is 0.0 and
      distance is None (we can't tell — treat as worst).
    """
    if target.lat is None or target.lon is None:
        return 1.0, None
    if comp_lat is None or comp_lon is None:
        return 0.0, None
    d = haversine_km(target.lat, target.lon, comp_lat, comp_lon)
    if target.radius_km <= 0:
        return (1.0 if d == 0 else 0.0), d
    score = max(0.0, 1.0 - d / target.radius_km)
    return score, d


def _recency_score(target: Target, comp_year: int | None, latest_year: int) -> float:
    if comp_year is None:
        return 0.0
    years_old = max(0, latest_year - comp_year)
    if target.max_years_old <= 0:
        return 1.0
    return max(0.0, 1.0 - years_old / target.max_years_old)


def _rooms_score(target: Target, comp_rooms: int | None) -> float:
    if target.rooms is None:
        return 0.7  # neutral — we can't judge
    if comp_rooms is None:
        return 0.5
    diff = abs(comp_rooms - target.rooms)
    if diff == 0:
        return 1.0
    if diff <= target.rooms_tol:
        return 0.7
    return 0.0


def _terrain_score(target_terrain: float, comp_terrain: float | None) -> float:
    """Score lot-size similarity for Maison.

    Uses ±50% tolerance (lots vary a lot). Linear decay from 1.0 at exact
    match to 0.0 at the tolerance edge.
    """
    if comp_terrain is None or comp_terrain <= 0:
        return 0.5  # neutral when data is missing
    if target_terrain <= 0:
        return 0.5
    err = abs(comp_terrain - target_terrain) / target_terrain
    return max(0.0, 1.0 - err / _TERRAIN_TOL)


def score_comp(comp: Comp, target: Target, *, latest_year: int) -> None:
    """Populate ``comp``'s score fields in-place given the ``target``."""
    comp.surface_score = _surface_score(target.surface, comp.surface)
    comp.distance_score, comp.distance_km = _distance_score(target, comp.lat, comp.lon)
    comp.recency_score = _recency_score(target, comp.year, latest_year)
    comp.rooms_score = _rooms_score(target, comp.rooms)

    # Use terrain-aware weights for Maison when the user provides a lot size.
    use_terrain = (
        target.type_local == "Maison"
        and target.surface_terrain is not None
        and target.surface_terrain > 0
    )

    if use_terrain:
        comp.terrain_score = _terrain_score(target.surface_terrain, comp.surface_terrain)
        comp.total_score = round(
            _W_SURFACE_T * comp.surface_score
            + _W_DISTANCE_T * comp.distance_score
            + _W_RECENCY_T * comp.recency_score
            + _W_ROOMS_T * comp.rooms_score
            + _W_TERRAIN * comp.terrain_score,
            4,
        )
    else:
        comp.total_score = round(
            _W_SURFACE * comp.surface_score
            + _W_DISTANCE * comp.distance_score
            + _W_RECENCY * comp.recency_score
            + _W_ROOMS * comp.rooms_score,
            4,
        )
