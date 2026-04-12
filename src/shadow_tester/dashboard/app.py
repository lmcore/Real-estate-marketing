"""Shadow Tester — Streamlit dashboard.

Run with:
    streamlit run src/shadow_tester/dashboard/app.py
    # or via the CLI entry point:
    shadow-tester dashboard
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Shadow Tester",
    page_icon="\U0001f3e0",
    layout="wide",
)

# ── Navigation ───────────────────────────────────────────────────────────

PAGES = {
    "\U0001f4ca March\u00e9": "market",
    "\U0001f50d Comparables": "comps",
    "\U0001f4cb Annonces": "listings",
    "\U0001f4b0 Forecaster": "forecaster",
}

st.sidebar.title("\U0001f3e0 Shadow Tester")
selection = st.sidebar.radio("Navigation", list(PAGES.keys()), label_visibility="collapsed")
page = PAGES[selection]

# ── Commune selector (shared across pages) ───────────────────────────────

commune = st.sidebar.text_input(
    "Commune (INSEE)", value="04112", help="Code INSEE, ex: 04112 = Manosque"
).strip().zfill(5)

# ── Page routing ─────────────────────────────────────────────────────────

if page == "market":
    from shadow_tester.dashboard.pages.market import render
    render(commune)
elif page == "comps":
    from shadow_tester.dashboard.pages.comps import render
    render(commune)
elif page == "listings":
    from shadow_tester.dashboard.pages.listings import render
    render(commune)
elif page == "forecaster":
    from shadow_tester.dashboard.pages.forecaster import render
    render(commune)
