"""Listings page — captured listings overview + stats by condition."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from shadow_tester.dashboard.helpers import (
    condition_emoji,
    condition_label,
    fmt_eur,
    fmt_pct,
)


def render(commune: str) -> None:
    st.header("\U0001f4cb Annonces captur\u00e9es")

    tab_stats, tab_list = st.tabs(["Statistiques par \u00e9tat", "Liste des annonces"])

    # ── Tab 1: Stats by condition ────────────────────────────────────────
    with tab_stats:
        type_filter = st.selectbox(
            "Type de bien", ["Tous", "Maison", "Appartement"], key="lst_type"
        )

        try:
            from shadow_tester.listings.stats import compute_listing_stats

            stats = compute_listing_stats(
                commune=commune,
                type_local=type_filter if type_filter != "Tous" else None,
            )
        except Exception:
            stats = None

        if stats and stats.total_listings > 0:
            c1, c2 = st.columns(2)
            c1.metric("Total annonces", stats.total_listings)
            c2.metric("Match\u00e9es DVF", stats.total_matched)

            rows = []
            for b in stats.buckets:
                rows.append({
                    "\u00c9tat": f"{condition_emoji(b.condition)} {condition_label(b.condition)}",
                    "Nb": b.count,
                    "Prix demand\u00e9": fmt_eur(b.median_price_asked),
                    "\u20ac/m\u00b2 demand\u00e9": fmt_eur(b.median_prix_m2_asked),
                    "Match\u00e9s": b.matched_count,
                    "N\u00e9go": fmt_pct(b.median_price_delta_pct, sign=True),
                    "D\u00e9lai (j)": b.median_days_to_sale or "-",
                    "\u20ac/m\u00b2 vendu": fmt_eur(b.median_prix_m2_sold),
                })

            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Chart: price_delta by condition.
            chart_data = [
                {"Condition": condition_label(b.condition), "N\u00e9go %": b.median_price_delta_pct}
                for b in stats.buckets
                if b.median_price_delta_pct is not None
            ]
            if chart_data:
                st.subheader("Marge de n\u00e9gociation par \u00e9tat")
                chart_df = pd.DataFrame(chart_data).set_index("Condition")
                st.bar_chart(chart_df)
        else:
            st.info(
                f"Aucune annonce captur\u00e9e pour {commune}. "
                "Utilisez `shadow-tester listings add` pour en ajouter."
            )

    # ── Tab 2: Listings list ─────────────────────────────────────────────
    with tab_list:
        try:
            from shadow_tester.listings import list_listings

            listings = list_listings(commune=commune)
        except Exception:
            listings = []

        if listings:
            rows = []
            for li in listings:
                rows.append({
                    "ID": li.id,
                    "Source": li.source or "-",
                    "Type": li.type_local or "-",
                    "Prix": fmt_eur(li.price_asked),
                    "Surface": f"{li.surface:.0f} m\u00b2" if li.surface else "-",
                    "Pi\u00e8ces": li.rooms or "-",
                    "\u00c9tat": condition_label(li.condition),
                    "Match DVF": li.matched_mutation_id or "-",
                    "Score": f"{li.match_score:.2f}" if li.match_score else "-",
                    "Premi\u00e8re vue": (li.first_seen or "")[:10],
                })

            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("Aucune annonce captur\u00e9e pour cette commune.")
