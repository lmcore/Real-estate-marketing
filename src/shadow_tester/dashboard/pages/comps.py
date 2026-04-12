"""Comparable properties page — interactive comps search."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from shadow_tester.dashboard.helpers import fmt_eur


def render(commune: str) -> None:
    st.header("\U0001f50d Biens comparables")

    with st.form("comps_form"):
        col1, col2, col3 = st.columns(3)
        type_local = col1.selectbox("Type", ["Maison", "Appartement"])
        surface = col2.number_input("Surface (m\u00b2)", min_value=10, max_value=500, value=100)
        rooms = col3.number_input("Pi\u00e8ces", min_value=1, max_value=20, value=4)

        col4, col5, col6 = st.columns(3)
        budget = col4.number_input("Budget (\u20ac)", min_value=0, value=0, step=10_000)
        terrain = col5.number_input(
            "Terrain (m\u00b2, Maison)", min_value=0, value=0, step=100,
            help="Lot size — active terrain scoring (25% weight) for Maison only.",
        )
        street = col6.text_input("Mot-cl\u00e9 voie", help="Filtre dur sur adresse_nom_voie.")

        col7, col8, col9 = st.columns(3)
        radius = col7.slider("Rayon (km)", 1.0, 20.0, 5.0, 0.5)
        years = col8.slider("Anciennet\u00e9 max (ans)", 1, 10, 5)
        limit = col9.number_input("Max r\u00e9sultats", min_value=1, max_value=50, value=10)

        submitted = st.form_submit_button("Rechercher")

    if submitted:
        from shadow_tester.comps import Target, find_comparables

        try:
            target = Target(
                commune=commune,
                type_local=type_local,
                surface=float(surface),
                rooms=int(rooms) if rooms else None,
                budget=float(budget) if budget > 0 else None,
                surface_terrain=float(terrain) if terrain > 0 else None,
                street_keyword=street.strip() or None,
                radius_km=radius,
                max_years_old=years,
                limit=limit,
            )
        except ValueError as exc:
            st.error(str(exc))
            return

        with st.spinner("Recherche en cours\u2026"):
            result = find_comparables(target)

        if not result.comps:
            st.warning(
                "Aucun comparable trouv\u00e9. Essayez d'\u00e9largir la surface, "
                "l'anciennet\u00e9 ou le rayon."
            )
            return

        # Summary metrics.
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Comparables", result.n_comps)
        m2.metric("Confiance", result.confidence)
        m3.metric("\u20ac/m\u00b2 m\u00e9dian", fmt_eur(result.median_prix_m2))
        m4.metric("Prix sugg\u00e9r\u00e9", fmt_eur(result.suggested_price_mid))

        # Fourchette.
        if result.suggested_price_low and result.suggested_price_high:
            st.info(
                f"Fourchette : {fmt_eur(result.suggested_price_low)} (P25) \u2014 "
                f"{fmt_eur(result.suggested_price_mid)} (m\u00e9diane) \u2014 "
                f"{fmt_eur(result.suggested_price_high)} (P75)"
            )

        # Verdict.
        if result.verdict:
            st.markdown(f"**\u2192 {result.verdict}**")

        # Comps table.
        rows = []
        for c in result.comps:
            rows.append({
                "Score": f"{c.total_score:.2f}",
                "Date": c.date_mutation,
                "Distance": f"{c.distance_km:.2f} km" if c.distance_km is not None else "-",
                "Surface": f"{c.surface:.0f} m\u00b2",
                "Pi\u00e8ces": c.rooms or "-",
                "\u00c9tat": (c.condition or "-").replace("_", " "),
                "Adresse": c.adresse,
                "Prix": fmt_eur(c.valeur_fonciere),
                "\u20ac/m\u00b2": fmt_eur(c.prix_m2),
            })

        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
