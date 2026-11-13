"""Vista Entrate."""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from src.metrics import (
    real_income,
    avg_monthly,
    typical_income,
    split_income,
)


# ---------------------------------------------------------------------------
# INCOME ANALYSIS
# ---------------------------------------------------------------------------

def render_income_analysis(full_df, filtered_df):
    st.subheader("💰 Analisi Entrate")

    full_income = real_income(full_df)
    full_income['date'] = pd.to_datetime(full_income['date'])

    if full_income.empty:
        st.info("Nessuna entrata trovata.")
        return

    typical_monthly = typical_income(full_df)
    mean_monthly = avg_monthly(full_df, 'income')

    filtered_income = real_income(filtered_df)
    total_period = filtered_income['amount'].sum()
    ord_inc_df, extra_inc_df = split_income(filtered_income)
    ord_period = ord_inc_df['amount'].sum() if not ord_inc_df.empty else 0
    extra_period = extra_inc_df['amount'].sum() if not extra_inc_df.empty else 0

    st.caption("Entrate reali (trasferimenti/saldo/aggiustamenti esclusi). "
               "Entrata tipica = mediana degli ultimi 12 mesi completi, robusta a tredicesima/bonus.")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Entrata Mensile Tipica", f"€{typical_monthly:,.0f}",
                help=f"Mediana ultimi 12 mesi completi (media €{mean_monthly:,.0f}).")
    col2.metric("Entrate Periodo", f"€{total_period:,.0f}",
                help=f"Ordinarie €{ord_period:,.0f} · Straordinarie €{extra_period:,.0f}")

    # Dipendenza dallo stipendio (quota delle entrate del periodo)
    sal_period = filtered_income[filtered_income['category'] == 'Stipendio']['amount'].sum() if not filtered_income.empty else 0
    dep_pct = (sal_period / total_period * 100) if total_period > 0 else 0
    col4.metric("Dipendenza da Stipendio", f"{dep_pct:.0f}%",
                help="Quota delle entrate del periodo che proviene dallo stipendio. "
                     "Più è alta, più il reddito dipende da un'unica fonte.")

    if extra_period > 0 and total_period > 0:
        st.caption(f"Nel periodo: entrate **ordinarie €{ord_period:,.0f}** · "
                   f"**straordinarie €{extra_period:,.0f}** (regali/bonus/rimborsi, "
                   f"{extra_period/total_period*100:.0f}% del totale).")

    # Annual Growth Rate
    st.markdown("### 📈 Crescita e andamento")
    annual_inc = full_income.groupby(full_income['date'].dt.year)['amount'].sum()

    selected_years = filtered_df['date'].dt.year.unique() if not filtered_df.empty else []
    target_year = None
    if len(selected_years) == 1:
        target_year = selected_years[0]
    elif not annual_inc.empty:
        target_year = annual_inc.index.max()

    if target_year and (target_year - 1) in annual_inc.index:
        today_ts = pd.Timestamp.today().normalize()
        if int(target_year) == today_ts.year:
            # Anno in corso: confronta lo STESSO periodo (1 gen → oggi) dei due anni
            cut_prev = today_ts - pd.DateOffset(years=1)
            current_val = full_income[(full_income['date'].dt.year == target_year)
                                      & (full_income['date'] <= today_ts)]['amount'].sum()
            prev_val = full_income[(full_income['date'].dt.year == target_year - 1)
                                   & (full_income['date'] <= cut_prev)]['amount'].sum()
            label = f"Crescita {target_year} vs {target_year - 1} (stesso periodo)"
        else:
            current_val = annual_inc[target_year]
            prev_val = annual_inc[target_year - 1]
            label = f"Crescita {target_year} vs {target_year - 1}"
        growth_pct = ((current_val - prev_val) / prev_val) * 100 if prev_val else 0.0
        col3.metric(label, f"{growth_pct:+.1f}%")
    else:
        col3.info(f"Dati anno precedente non disponibili.")

    fig_annual = px.bar(x=annual_inc.index, y=annual_inc.values,
                        title="Entrate per anno", labels={'x': 'Anno', 'y': 'Entrate totali'})
    st.plotly_chart(fig_annual, use_container_width=True)

    st.divider()

    # --- Andamento Stipendio (voce singola) ---
    st.markdown("### 💼 Andamento Stipendio")
    st.caption("Analisi della sola voce 'Stipendio' per capire se sta salendo o scendendo.")

    salary = full_income[full_income['category'] == 'Stipendio'].copy()
    if salary.empty:
        st.info("Nessuna voce 'Stipendio' trovata tra le entrate.")
    else:
        monthly_sal = salary.groupby(pd.Grouper(key='date', freq='ME'))['amount'].sum()
        monthly_sal = monthly_sal[monthly_sal > 0]

        last_sal = monthly_sal.iloc[-1]
        avg_sal = monthly_sal.mean()

        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Ultimo Stipendio Mensile", f"€{last_sal:,.0f}")
        sc2.metric("Media Mensile", f"€{avg_sal:,.0f}")
        if len(monthly_sal) >= 2:
            prev_sal = monthly_sal.iloc[-2]
            diff = last_sal - prev_sal
            pct = (diff / prev_sal * 100) if prev_sal else 0
            sc3.metric("Mese Precedente", f"€{prev_sal:,.0f}",
                       delta=f"{diff:+,.0f}€ ({pct:+.1f}%)")
        else:
            sc3.metric("Mese Precedente", "N/A")

        # Trend complessivo via regressione lineare
        if len(monthly_sal) >= 3:
            x = np.arange(len(monthly_sal))
            slope = np.polyfit(x, monthly_sal.values, 1)[0]
            if slope > 5:
                st.success(f"📈 Lo stipendio è in **crescita** (~{slope:+,.0f} €/mese di trend)")
            elif slope < -5:
                st.error(f"📉 Lo stipendio è in **calo** (~{slope:+,.0f} €/mese di trend)")
            else:
                st.info(f"➡️ Lo stipendio è **stabile** (~{slope:+,.0f} €/mese di trend)")

        # Grafico mensile con media mobile
        sal_df = monthly_sal.reset_index()
        sal_df.columns = ['date', 'amount']
        fig_sal = go.Figure()
        fig_sal.add_trace(go.Bar(x=sal_df['date'], y=sal_df['amount'],
                                 name='Stipendio', marker_color='#00CC96', opacity=0.8))
        if len(sal_df) >= 3:
            sal_df['ma3'] = sal_df['amount'].rolling(3, min_periods=1).mean()
            fig_sal.add_trace(go.Scatter(x=sal_df['date'], y=sal_df['ma3'],
                                         name='Media mobile 3m', mode='lines+markers',
                                         line=dict(color='#EF553B', width=2, dash='dot')))
        fig_sal.update_layout(title="Stipendio Mensile nel Tempo", xaxis_title="Mese",
                              yaxis_title="€", hovermode="x unified", height=380)
        st.plotly_chart(fig_sal, use_container_width=True)

        # Confronto stipendio annuale totale
        annual_sal = salary.groupby(salary['date'].dt.year)['amount'].sum()
        if len(annual_sal) >= 2:
            asal_df = annual_sal.reset_index()
            asal_df.columns = ['Anno', 'Stipendio']
            asal_df['Anno'] = asal_df['Anno'].astype(str)
            fig_asal = px.bar(asal_df, x='Anno', y='Stipendio', text_auto='.2s',
                              title="Stipendio Annuale Totale",
                              color_discrete_sequence=['#00CC96'])
            fig_asal.update_layout(height=320)
            st.plotly_chart(fig_asal, use_container_width=True)

        # Dipendenza dallo stipendio nel tempo (stipendio vs altre entrate)
        fi = full_income.copy()
        fi['mese'] = fi['date'].dt.to_period('M').astype(str)
        fi['fonte'] = fi['category'].apply(lambda c: 'Stipendio' if c == 'Stipendio' else 'Altre entrate')
        comp = fi.groupby(['mese', 'fonte'])['amount'].sum().reset_index()
        if not comp.empty:
            fig_dep = px.area(comp, x='mese', y='amount', color='fonte',
                              title="Stipendio vs Altre Entrate nel Tempo",
                              labels={'amount': '€', 'mese': 'Mese', 'fonte': 'Fonte'},
                              color_discrete_map={'Stipendio': '#00CC96', 'Altre entrate': '#636EFA'})
            fig_dep.update_layout(height=340, hovermode='x unified')
            st.plotly_chart(fig_dep, use_container_width=True)

    st.divider()

    st.markdown("### 🏦 Fonti di entrata")
    if not filtered_income.empty:
        filtered_income['date'] = pd.to_datetime(filtered_income['date'])
        inc_by_cat = filtered_income.groupby('category')['amount'].sum().reset_index()
        fig_pie = px.pie(inc_by_cat, values='amount', names='category',
                         title="Composizione entrate (periodo selezionato)", hole=0.4)

        monthly_cat = filtered_income.groupby([pd.Grouper(key='date', freq='ME'), 'category'])['amount'].sum().reset_index()
        fig_stack = px.bar(monthly_cat, x='date', y='amount', color='category',
                           title="Fonti di entrata nel tempo")

        c1, c2 = st.columns(2)
        c1.plotly_chart(fig_pie, use_container_width=True)
        c2.plotly_chart(fig_stack, use_container_width=True)
