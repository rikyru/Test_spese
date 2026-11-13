"""Vista Necessità vs Desideri."""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from src.metrics import (
    real_income,
    real_expenses,
)


# ---------------------------------------------------------------------------
# NEEDS VS WANTS
# ---------------------------------------------------------------------------

def render_needs_vs_wants(full_df, filtered_df=None):
    st.subheader("⚖️ Necessità vs Desideri")

    # Accept both old (single df) and new (full_df, filtered_df) signatures
    if filtered_df is None:
        filtered_df = full_df

    df = filtered_df.copy()

    if 'necessity' not in df.columns:
        st.warning("Classificazione Necessità/Desiderio mancante: applica le regole da Impostazioni.")
        return

    df['date'] = pd.to_datetime(df['date'])
    df['month_year'] = df['date'].dt.to_period('M').astype(str)
    expenses = real_expenses(df)
    expenses['abs_amount'] = expenses['amount'].abs()

    if expenses.empty:
        st.info("Nessuna spesa nel periodo selezionato.")
        return

    # Stacked bar over time
    nw_grouped = expenses.groupby(['month_year', 'necessity'])['abs_amount'].sum().reset_index()
    fig_nw = px.bar(nw_grouped, x='month_year', y='abs_amount', color='necessity',
                    title="Necessità vs Desideri nel tempo", barmode='stack',
                    color_discrete_map={'Need': '#4CAF50', 'Want': '#FF7043'},
                    category_orders={"necessity": ["Need", "Want"]})
    fig_nw.update_layout(xaxis_title="Mese", yaxis_title="€")
    st.plotly_chart(fig_nw, use_container_width=True)

    # Current period breakdown
    total_exp = expenses['abs_amount'].sum()
    needs_total = expenses[expenses['necessity'] == 'Need']['abs_amount'].sum()
    wants_total = expenses[expenses['necessity'] == 'Want']['abs_amount'].sum()

    needs_pct = (needs_total / total_exp * 100) if total_exp > 0 else 0
    wants_pct = (wants_total / total_exp * 100) if total_exp > 0 else 0

    col1, col2, col3 = st.columns(3)
    col1.metric("Necessità (Need)", f"€{needs_total:,.2f}", f"{needs_pct:.0f}% del totale")
    col2.metric("Desideri (Want)", f"€{wants_total:,.2f}", f"{wants_pct:.0f}% del totale")
    col3.metric("Totale Spese", f"€{total_exp:,.2f}")

    unclassified = total_exp - needs_total - wants_total
    if unclassified > 0.5:
        st.caption(f"⚠️ €{unclassified:,.2f} ({unclassified / total_exp * 100:.0f}%) senza classificazione Need/Want — "
                   "impostabile in Impostazioni → Necessità o desiderio.")

    # 50/30/20 Rule comparison
    st.markdown("### 🎯 Regola 50/30/20")
    st.caption("Obiettivo: 50% Bisogni · 30% Desideri · 20% Risparmio")

    # Estimate income for the period
    income_df = real_income(filtered_df) if filtered_df is not None else pd.DataFrame()
    total_income = income_df['amount'].sum() if not income_df.empty else 0
    if st.session_state.get('ana_my_share'):
        # Spese alla quota stimata vs entrate reali (con i rimborsi): il confronto non torna
        st.info("Con «Mia quota» attivo la regola 50/30/20 non è mostrata: confronterebbe "
                "spese stimate con entrate reali. Spegni l'interruttore per vederla.")
        total_income = 0

    if total_income > 0:
        target_needs = total_income * 0.50
        target_wants = total_income * 0.30
        target_savings = total_income * 0.20
        actual_savings = total_income - total_exp

        rule_data = {
            'Voce': ['Needs (50%)', 'Wants (30%)', 'Risparmio (20%)'],
            'Target': [target_needs, target_wants, target_savings],
            'Attuale': [needs_total, wants_total, max(actual_savings, 0)],
        }
        rule_df = pd.DataFrame(rule_data)
        rule_df['Scostamento'] = rule_df['Attuale'] - rule_df['Target']
        rule_df['Stato'] = rule_df.apply(
            lambda r: '✅' if abs(r['Scostamento']) / r['Target'] < 0.1
            else ('⚠️' if abs(r['Scostamento']) / r['Target'] < 0.25 else '🔴'), axis=1
        )

        fig_rule = go.Figure()
        fig_rule.add_trace(go.Bar(name='Target', x=rule_df['Voce'], y=rule_df['Target'],
                                   marker_color='#B0BEC5', opacity=0.6))
        fig_rule.add_trace(go.Bar(name='Attuale', x=rule_df['Voce'], y=rule_df['Attuale'],
                                   marker_color=['#4CAF50', '#FF7043', '#2196F3']))
        fig_rule.update_layout(barmode='group', title="50/30/20 — Target vs Attuale",
                                yaxis_title="€", height=350)
        st.plotly_chart(fig_rule, use_container_width=True)

        display_rule = rule_df.copy()
        display_rule['Target'] = display_rule['Target'].apply(lambda x: f"€{x:,.0f}")
        display_rule['Attuale'] = display_rule['Attuale'].apply(lambda x: f"€{x:,.0f}")
        display_rule['Scostamento'] = display_rule['Scostamento'].apply(lambda x: f"{'+' if x >= 0 else ''}€{x:,.0f}")
        st.dataframe(display_rule[['Voce', 'Target', 'Attuale', 'Scostamento', 'Stato']],
                     use_container_width=True, hide_index=True)
    elif not st.session_state.get('ana_my_share'):
        st.info("Aggiungi dati di entrata per vedere il confronto con la regola 50/30/20.")
