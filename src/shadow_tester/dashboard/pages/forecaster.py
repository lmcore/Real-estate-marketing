"""Forecaster page — interactive profit-margin calculator."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from shadow_tester.dashboard.helpers import fmt_eur, fmt_pct, roi_color


def render(commune: str) -> None:
    st.header("\U0001f4b0 Forecaster \u2014 marge apr\u00e8s travaux")

    tab_calc, tab_saved = st.tabs(["Calculer", "Sc\u00e9narios sauvegard\u00e9s"])

    # ── Tab 1: Calculator ────────────────────────────────────────────────
    with tab_calc:
        with st.form("forecast_form"):
            st.subheader("Param\u00e8tres du projet")

            col1, col2, col3 = st.columns(3)
            type_local = col1.selectbox("Type", ["Maison", "Appartement"])
            surface = col2.number_input("Surface (m\u00b2)", min_value=10, max_value=500, value=100)
            rooms = col3.number_input("Pi\u00e8ces", min_value=0, max_value=20, value=4)

            col4, col5 = st.columns(2)
            prix_achat = col4.number_input(
                "Prix d'achat (\u20ac)", min_value=1000, value=200_000, step=5_000
            )
            travaux = col5.number_input(
                "Travaux TTC (\u20ac)", min_value=0, value=50_000, step=5_000
            )

            col6, col7, col8 = st.columns(3)
            condition_achat = col6.selectbox(
                "Condition achat",
                ["a_renover", "brut", "partiel", "renove"],
                index=0,
            )
            condition_revente = col7.selectbox(
                "Condition revente",
                ["renove", "partiel"],
                index=0,
            )
            portage_mois = col8.number_input(
                "Dur\u00e9e portage (mois)", min_value=1, max_value=60, value=12,
            )

            st.subheader("Frais MDB")
            fc1, fc2, fc3, fc4 = st.columns(4)
            notaire_pct = fc1.number_input(
                "Notaire (%)", min_value=0.0, max_value=15.0, value=2.5, step=0.1,
            )
            tva_pct = fc2.number_input(
                "TVA marge (%)", min_value=0.0, max_value=30.0, value=20.0, step=1.0,
            )
            portage_pct = fc3.number_input(
                "Portage (%/mois)", min_value=0.0, max_value=3.0, value=0.5, step=0.1,
            )
            agence_pct = fc4.number_input(
                "Agence revente (%)", min_value=0.0, max_value=10.0, value=0.0, step=0.5,
            )

            label = st.text_input("Nom du sc\u00e9nario (optionnel)")
            save_it = st.checkbox("Sauvegarder en base", value=True)

            submitted = st.form_submit_button("Calculer la marge")

        if submitted:
            from shadow_tester.forecaster import (
                ForecastParams,
                calculate_forecast,
                save_forecast,
            )

            try:
                params = ForecastParams(
                    commune=commune,
                    type_local=type_local,
                    surface=float(surface),
                    prix_achat=float(prix_achat),
                    travaux=float(travaux),
                    rooms=int(rooms) if rooms else None,
                    condition_achat=condition_achat,
                    condition_revente=condition_revente,
                    portage_mois=int(portage_mois),
                    frais_notaire_pct=notaire_pct / 100,
                    tva_marge_pct=tva_pct / 100,
                    portage_mensuel_pct=portage_pct / 100,
                    frais_agence_pct=agence_pct / 100,
                    label=label.strip() or None,
                )
            except ValueError as exc:
                st.error(str(exc))
                return

            with st.spinner("Calcul en cours\u2026"):
                result = calculate_forecast(params)

            # Investment breakdown.
            st.subheader("Investissement")
            ic1, ic2, ic3, ic4 = st.columns(4)
            ic1.metric("Prix achat", fmt_eur(result.prix_achat))
            ic2.metric("Frais notaire", fmt_eur(result.frais_notaire))
            ic3.metric("Travaux", fmt_eur(result.travaux))
            ic4.metric("Portage", fmt_eur(result.frais_portage))
            st.metric("Total investissement", fmt_eur(result.total_investissement))

            # Resale estimate.
            if result.prix_revente_mid is not None:
                st.subheader(
                    f"Revente estim\u00e9e ({result.n_comps} comps, confiance {result.confidence})"
                )
                rc1, rc2, rc3 = st.columns(3)
                rc1.metric("Bas (P25)", fmt_eur(result.prix_revente_low))
                rc2.metric("M\u00e9dian", fmt_eur(result.prix_revente_mid))
                rc3.metric("Haut (P75)", fmt_eur(result.prix_revente_high))

                # Margin breakdown.
                st.subheader("Marge")
                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("Marge brute", fmt_eur(result.marge_brute))
                mc2.metric("TVA sur marge", fmt_eur(result.tva_sur_marge))
                mc3.metric("Frais agence", fmt_eur(result.frais_agence))

                color = roi_color(result.roi_pct)
                st.markdown(
                    f"### Marge nette : "
                    f"<span style='color:{color}'>{fmt_eur(result.marge_nette)}</span>",
                    unsafe_allow_html=True,
                )
                if result.roi_pct is not None:
                    st.markdown(
                        f"**ROI** : {fmt_pct(result.roi_pct, sign=True)} "
                        f"| **ROI annualis\u00e9** : {fmt_pct(result.roi_annualise_pct, sign=True)}"
                    )

                if result.marge_nette_low is not None and result.marge_nette_high is not None:
                    st.info(
                        f"Fourchette nette : {fmt_eur(result.marge_nette_low)} (bas) \u2014 "
                        f"{fmt_eur(result.marge_nette_high)} (haut)"
                    )
            else:
                st.warning("Pas assez de comparables pour estimer la revente.")

            if result.verdict:
                st.markdown(f"**\u2192 {result.verdict}**")

            if save_it:
                save_forecast(result)
                st.success(f"Forecast sauv\u00e9 (id={result.id})")

    # ── Tab 2: Saved scenarios ───────────────────────────────────────────
    with tab_saved:
        try:
            from shadow_tester.forecaster import list_forecasts

            forecasts = list_forecasts(commune=commune)
        except Exception:
            forecasts = []

        if forecasts:
            rows = []
            for f in forecasts:
                rows.append({
                    "ID": f.id,
                    "Date": (f.created_at or "")[:10],
                    "Label": f.params.label or "-",
                    "Type": f.params.type_local,
                    "Surface": f"{f.params.surface:.0f}",
                    "Achat": fmt_eur(f.prix_achat),
                    "Travaux": fmt_eur(f.travaux),
                    "Revente": fmt_eur(f.prix_revente_mid),
                    "Marge nette": fmt_eur(f.marge_nette),
                    "ROI": fmt_pct(f.roi_pct, sign=True),
                })

            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("Aucun forecast sauvegard\u00e9 pour cette commune.")
