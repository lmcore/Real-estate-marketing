"""Tests for dashboard helper functions (no Streamlit dependency)."""

from __future__ import annotations

from shadow_tester.dashboard.helpers import (
    condition_emoji,
    condition_label,
    fmt_eur,
    fmt_num,
    fmt_pct,
    roi_color,
)

# ── fmt_eur ──────────────────────────────────────────────────────────────


def test_fmt_eur_integer():
    result = fmt_eur(270_000)
    assert "\u20ac" in result
    assert "270" in result


def test_fmt_eur_none():
    assert fmt_eur(None) == "-"


def test_fmt_eur_with_decimals():
    result = fmt_eur(2800.55, decimals=2)
    assert "2800" in result.replace("\u202f", "")
    assert ".55" in result


def test_fmt_eur_zero():
    result = fmt_eur(0)
    assert "0" in result


# ── fmt_pct ──────────────────────────────────────────────────────────────


def test_fmt_pct_basic():
    result = fmt_pct(6.5)
    assert "6.5" in result
    assert "%" in result


def test_fmt_pct_none():
    assert fmt_pct(None) == "-"


def test_fmt_pct_signed_positive():
    result = fmt_pct(10.0, sign=True)
    assert result.startswith("+")


def test_fmt_pct_signed_negative():
    result = fmt_pct(-5.0, sign=True)
    assert "-5.0" in result


# ── fmt_num ──────────────────────────────────────────────────────────────


def test_fmt_num_basic():
    result = fmt_num(22_400)
    assert "22" in result
    assert "400" in result


def test_fmt_num_none():
    assert fmt_num(None) == "-"


# ── condition_label ──────────────────────────────────────────────────────


def test_condition_label_known():
    assert "nover" in condition_label("a_renover").lower()


def test_condition_label_renove():
    assert "nov" in condition_label("renove").lower()


def test_condition_label_none():
    assert condition_label(None) == "-"


def test_condition_label_unknown_passthrough():
    assert condition_label("xyz") == "xyz"


# ── condition_emoji ──────────────────────────────────────────────────────


def test_condition_emoji_brut():
    assert condition_emoji("brut") != ""


def test_condition_emoji_none():
    assert condition_emoji(None) == ""


# ── roi_color ────────────────────────────────────────────────────────────


def test_roi_color_excellent():
    assert roi_color(25.0) == "green"


def test_roi_color_good():
    assert roi_color(15.0) == "limegreen"


def test_roi_color_ok():
    assert roi_color(7.0) == "orange"


def test_roi_color_risky():
    assert roi_color(2.0) == "darkorange"


def test_roi_color_negative():
    assert roi_color(-5.0) == "red"


def test_roi_color_none():
    assert roi_color(None) == "gray"
