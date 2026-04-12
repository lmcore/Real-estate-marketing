"""Market overview page — DVF stats + INSEE indicators."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from shadow_tester.dashboard.helpers import fmt_eur, fmt_num, fmt_pct


def render(commune: str) -> None:
    st.header("\U0001f4ca Vue march\u00e9")

    # ── INSEE indicators ─────────────────────────────────────────────────
    try:
        from shadow_tester.insee import summarize_commune

        summary = summarize_commune(commune)
    except Exception:
        summary = None

    if summary and summary.population:
        st.subheader("Indicateurs INSEE")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Population", fmt_num(summary.population))
        c2.metric("Densit\u00e9", f"{fmt_num(summary.densite_hab_km2)} hab/km\u00b2")
        c3.metric("Revenu m\u00e9dian / UC", fmt_eur(summary.revenu_median_uc))
        c4.metric("Taux de vacance", fmt_pct(summary.taux_vacance))

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Part propri\u00e9taires", fmt_pct(summary.part_proprietaires))
        c6.metric("Ch\u00f4mage 15-64", fmt_pct(summary.taux_chomage_1564))
        if summary.affordability_years_maison:
            c7.metric("Affordability Maison", f"{summary.affordability_years_maison:.1f}x")
        if summary.affordability_years_appartement:
            c8.metric("Affordability Appart.", f"{summary.affordability_years_appartement:.1f}x")
        st.divider()

    # ── DVF stats ────────────────────────────────────────────────────────
    try:
        from shadow_tester.dvf import compute_commune_stats

        stats = compute_commune_stats(commune)
    except Exception:
        stats = None

    if stats and stats.buckets:
        st.subheader(f"Transactions DVF \u2014 {stats.total_transactions} au total")

        rows = []
        for b in stats.buckets:
            rows.append({
                "Type": b.type_local,
                "Ann\u00e9e": b.year,
                "Nb": b.n_transactions,
                "M\u00e9dian \u20ac/m\u00b2": b.median_prix_m2,
                "P25 \u20ac/m\u00b2": b.p25_prix_m2,
                "P75 \u20ac/m\u00b2": b.p75_prix_m2,
                "Surface m\u00e9d.": b.median_surface,
                "Prix m\u00e9dian": b.median_valeur,
            })

        df = pd.DataFrame(rows)
        if not df.empty:
            # Filter controls.
            col_type, col_year = st.columns(2)
            types = ["Tous", *sorted(df["Type"].dropna().unique().tolist())]
            selected_type = col_type.selectbox("Type de bien", types)
            years = ["Toutes", *sorted(df["Ann\u00e9e"].dropna().unique().tolist(), reverse=True)]
            selected_year = col_year.selectbox("Ann\u00e9e", years)

            view = df.copy()
            if selected_type != "Tous":
                view = view[view["Type"] == selected_type]
            if selected_year != "Toutes":
                view = view[view["Ann\u00e9e"] == selected_year]

            st.dataframe(
                view.style.format({
                    "M\u00e9dian \u20ac/m\u00b2": "{:,.0f}",
                    "P25 \u20ac/m\u00b2": "{:,.0f}",
                    "P75 \u20ac/m\u00b2": "{:,.0f}",
                    "Surface m\u00e9d.": "{:,.0f}",
                    "Prix m\u00e9dian": "{:,.0f}",
                }, na_rep="-"),
                use_container_width=True,
                hide_index=True,
            )

            # Chart: prix/m² over time.
            chart_df = df[df["M\u00e9dian \u20ac/m\u00b2"].notna()].copy()
            if not chart_df.empty and len(chart_df["Ann\u00e9e"].unique()) > 1:
                st.subheader("\u00c9volution prix/m\u00b2")
                pivot = chart_df.pivot_table(
                    index="Ann\u00e9e", columns="Type", values="M\u00e9dian \u20ac/m\u00b2",
                )
                st.line_chart(pivot)
    else:
        st.info(
            f"Aucune donn\u00e9e DVF pour la commune {commune}. "
            "Lancez `shadow-tester dvf ingest --commune {commune} --years 2020-2024` d'abord."
        )
