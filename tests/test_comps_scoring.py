"""Unit tests for comps.scoring (haversine + subscores)."""

from __future__ import annotations

import math

import pytest

from shadow_tester.comps.models import Comp, Target
from shadow_tester.comps.scoring import haversine_km, score_comp


def _make_comp(**overrides) -> Comp:
    defaults = dict(
        id_mutation="x",
        date_mutation="2024-06-01",
        year=2024,
        type_local="Maison",
        surface=100.0,
        rooms=4,
        valeur_fonciere=280_000.0,
        prix_m2=2800.0,
        adresse="rue de test",
        lat=None,
        lon=None,
    )
    defaults.update(overrides)
    return Comp(**defaults)


def test_haversine_same_point_is_zero():
    assert haversine_km(43.8, 5.78, 43.8, 5.78) == pytest.approx(0.0, abs=1e-9)


def test_haversine_manosque_to_volx_is_about_9km():
    # Manosque centre ~ (43.833, 5.783), Volx centre ~ (43.881, 5.833)
    d = haversine_km(43.833, 5.783, 43.881, 5.833)
    assert 5.0 < d < 10.0


def test_haversine_one_degree_lat_is_about_111km():
    d = haversine_km(43.0, 5.0, 44.0, 5.0)
    assert 110.0 < d < 112.0


def test_target_validates_type_local():
    with pytest.raises(ValueError):
        Target(commune="04112", type_local="Chateau", surface=100)


def test_target_validates_positive_surface():
    with pytest.raises(ValueError):
        Target(commune="04112", type_local="Maison", surface=-10)


def test_target_surface_window():
    t = Target(commune="04112", type_local="Maison", surface=100, surface_tol=0.2)
    assert t.surface_min == pytest.approx(80.0)
    assert t.surface_max == pytest.approx(120.0)


def test_target_zero_pads_commune():
    t = Target(commune="4112", type_local="Maison", surface=100)
    assert t.commune == "04112"


def test_score_perfect_match_is_one():
    target = Target(
        commune="04112",
        type_local="Maison",
        surface=100,
        rooms=4,
        lat=43.833,
        lon=5.783,
    )
    comp = _make_comp(surface=100.0, rooms=4, year=2024, lat=43.833, lon=5.783)
    score_comp(comp, target, latest_year=2024)
    assert comp.surface_score == pytest.approx(1.0)
    assert comp.distance_score == pytest.approx(1.0)
    assert comp.rooms_score == pytest.approx(1.0)
    assert comp.recency_score == pytest.approx(1.0)
    assert comp.total_score == pytest.approx(1.0)
    assert comp.distance_km == pytest.approx(0.0, abs=1e-3)


def test_score_surface_decays_linearly():
    target = Target(commune="04112", type_local="Maison", surface=100)
    comp_100 = _make_comp(surface=100)
    comp_120 = _make_comp(surface=120)
    comp_150 = _make_comp(surface=150)
    score_comp(comp_100, target, latest_year=2024)
    score_comp(comp_120, target, latest_year=2024)
    score_comp(comp_150, target, latest_year=2024)
    assert comp_100.surface_score == pytest.approx(1.0)
    assert comp_120.surface_score == pytest.approx(0.8, rel=1e-3)
    assert comp_150.surface_score == pytest.approx(0.5, rel=1e-3)


def test_score_distance_zero_without_anchor():
    """Without lat/lon on the target, distance_score is 1.0 (neutral)."""
    target = Target(commune="04112", type_local="Maison", surface=100)
    comp = _make_comp(lat=43.5, lon=5.5)
    score_comp(comp, target, latest_year=2024)
    assert comp.distance_score == pytest.approx(1.0)
    assert comp.distance_km is None


def test_score_distance_penalises_far_comps_with_anchor():
    target = Target(
        commune="04112",
        type_local="Maison",
        surface=100,
        lat=43.833,
        lon=5.783,
        radius_km=5.0,
    )
    near = _make_comp(lat=43.833, lon=5.783)     # 0 km
    far = _make_comp(lat=43.880, lon=5.840)       # ~6–7 km away → beyond radius
    score_comp(near, target, latest_year=2024)
    score_comp(far, target, latest_year=2024)
    assert near.distance_score > far.distance_score
    assert far.distance_score == pytest.approx(0.0)


def test_score_rooms_tolerance():
    target = Target(commune="04112", type_local="Maison", surface=100, rooms=4, rooms_tol=1)
    exact = _make_comp(rooms=4)
    close = _make_comp(rooms=5)
    far = _make_comp(rooms=7)
    for c in (exact, close, far):
        score_comp(c, target, latest_year=2024)
    assert exact.rooms_score == pytest.approx(1.0)
    assert close.rooms_score == pytest.approx(0.7)
    assert far.rooms_score == pytest.approx(0.0)


def test_score_recency_decays_over_years():
    target = Target(commune="04112", type_local="Maison", surface=100, max_years_old=5)
    recent = _make_comp(year=2024)
    mid = _make_comp(year=2022)
    old = _make_comp(year=2020)
    for c in (recent, mid, old):
        score_comp(c, target, latest_year=2024)
    assert recent.recency_score > mid.recency_score > old.recency_score
    assert old.recency_score == pytest.approx(0.2, rel=1e-3)


def test_score_total_in_unit_interval():
    target = Target(
        commune="04112",
        type_local="Maison",
        surface=100,
        rooms=4,
        lat=43.833,
        lon=5.783,
    )
    comp = _make_comp(surface=85, rooms=3, year=2022, lat=43.84, lon=5.79)
    score_comp(comp, target, latest_year=2024)
    assert 0.0 <= comp.total_score <= 1.0
    assert not math.isnan(comp.total_score)
