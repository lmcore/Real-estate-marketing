"""Market overview page — DVF stats + INSEE indicators + auto-ingestion."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from shadow_tester.dashboard.helpers import fmt_eur, fmt_num, fmt_pct


def _has_dvf_data(commune: str) -> bool:
    """Quick check whether any DVF rows exist for this commune."""
    from shadow_tester.storage import connect

    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM dvf_transactions WHERE code_commune = ?",
            (commune,),
        ).fetchone()
    return row is not None and row[0] > 0


def _ingest_dvf(commune: str, years: list[int]) -> int:
    """Ingest DVF data and return number of rows loaded."""
    from shadow_tester.dvf import ingest_commune_years

    total = 0
    for year in years:
        n = ingest_commune_years(commune, [year])
        total += n
    return total


def render(commune: str) -> None:
    st.header("\U0001f4ca Vue march\u00e9")

    # ── Auto-ingestion when no data ──────────────────────────────────────
    if not _has_dvf_data(commune):
        st.warning(
            f"Aucune donn\u00e9e DVF pour la commune **{commune}**. "
            "Cliquez ci-dessous pour t\u00e9l\u00e9charger les transactions depuis data.gouv.fr."
        )
        col_y1, col_y2 = st.columns(2)
        year_start = col_y1.number_input("Ann\u00e9e d\u00e9but", value=2020, min_value=2014, max_value=2025)
        year_end = col_y2.number_input("Ann\u00e9e fin", value=2024, min_value=2014, max_value=2025)

        if st.button("\U0001f4e5 T\u00e9l\u00e9charger les donn\u00e9es DVF", type="primary"):
            years = list(range(int(year_start), int(year_end) + 1))
            with st.spinner(f"T\u00e9l\u00e9chargement DVF {years[0]}\u2013{years[-1]} pour {commune}\u2026"):
                try:
                    total = _ingest_dvf(commune, years)
                    st.success(f"{total} transactions charg\u00e9es !")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Erreur lors de l'ingestion : {exc}")
        return

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

        # Re-ingest button at the bottom.
        with st.expander("\U0001f504 Mettre \u00e0 jour les donn\u00e9es DVF"):
            col_y1, col_y2 = st.columns(2)
            year_s = col_y1.number_input(
                "D\u00e9but", value=2020, min_value=2014, max_value=2025, key="re_y1"
            )
            year_e = col_y2.number_input(
                "Fin", value=2024, min_value=2014, max_value=2025, key="re_y2"
            )
            if st.button("\U0001f504 Re-t\u00e9l\u00e9charger"):
                yrs = list(range(int(year_s), int(year_e) + 1))
                with st.spinner("T\u00e9l\u00e9chargement\u2026"):
                    try:
                        total = _ingest_dvf(commune, yrs)
                        st.success(f"{total} transactions charg\u00e9es !")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Erreur : {exc}")
    else:
        st.info("Aucune transaction DVF trouv\u00e9e avec ces filtres.")
