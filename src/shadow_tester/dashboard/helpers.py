"""Pure helper functions for the Streamlit dashboard — no Streamlit imports."""

from __future__ import annotations


def fmt_eur(v: float | int | None, *, decimals: int = 0) -> str:
    """Format a numeric value as euros with French spacing."""
    if v is None:
        return "-"
    return f"{v:,.{decimals}f} \u20ac".replace(",", "\u202f")


def fmt_pct(v: float | None, *, decimals: int = 1, sign: bool = False) -> str:
    """Format a percentage value."""
    if v is None:
        return "-"
    prefix = "+" if sign and v > 0 else ""
    return f"{prefix}{v:.{decimals}f}\u202f%"


def fmt_num(v: float | int | None, *, decimals: int = 0) -> str:
    """Format a number with French spacing."""
    if v is None:
        return "-"
    return f"{v:,.{decimals}f}".replace(",", "\u202f")


def condition_label(cond: str | None) -> str:
    """Human-readable French label for a condition bucket."""
    _LABELS = {
        "brut": "Brut (gros \u0153uvre)",
        "a_renover": "\u00c0 r\u00e9nover",
        "partiel": "R\u00e9novation partielle",
        "renove": "R\u00e9nov\u00e9",
        "inconnu": "Inconnu",
    }
    if cond is None:
        return "-"
    return _LABELS.get(cond, cond)


def condition_emoji(cond: str | None) -> str:
    """Emoji prefix for a condition bucket (visual cue)."""
    _EMOJIS = {
        "brut": "\U0001f6a7",
        "a_renover": "\U0001f527",
        "partiel": "\U0001f3d7\ufe0f",
        "renove": "\u2728",
        "inconnu": "\u2753",
    }
    return _EMOJIS.get(cond or "", "")


def roi_color(roi: float | None) -> str:
    """Return a CSS-safe color for an ROI value."""
    if roi is None:
        return "gray"
    if roi >= 20:
        return "green"
    if roi >= 10:
        return "limegreen"
    if roi >= 5:
        return "orange"
    if roi >= 0:
        return "darkorange"
    return "red"
