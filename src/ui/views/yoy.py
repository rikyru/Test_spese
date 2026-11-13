"""Vista Anno vs Anno."""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from src.metrics import (
    real_income,
    real_expenses,
)


# ---------------------------------------------------------------------------
# YOY COMPARISON
# ---------------------------------------------------------------------------

def render_yoy_comparison(full_df):
    from datetime import date as date_type
    st.subheader("📅 Confronto Anno vs Anno")

    today = date_type.today()

    df = full_df.copy()
    df['date'] = pd.to_datetime(df['date'])

    st.caption("Entrate/spese reali: trasferimenti interni, saldo iniziale e aggiustamenti esclusi.")

    years = sorted(df['date'].dt.year.dropna().unique().tolist())
    if not years:
        st.info("Dati insufficienti per il confronto anno su anno.")
        return

    c_a, c_b, c_mode = st.columns([1, 1, 2])
    current_year = c_a.selectbox("Anno", years, index=len(years) - 1, key='yoy_year_a')
    b_options = [y for y in years if y != current_year] or [current_year]
    default_b_idx = b_options.index(current_year - 1) if (current_year - 1) in b_options else len(b_options) - 1
    prev_year = c_b.selectbox("Confronta con", b_options, index=default_b_idx, key='yoy_year_b')
    # Se l'anno scelto è quello in corso, di default confronta lo STESSO periodo:
    # un anno incompleto contro uno intero sembrerebbe sempre in calo.
    period_mode = c_mode.radio(
        "Periodo", ["Anno intero", "Fino a oggi (YTD)"],
        index=1 if current_year == today.year else 0,
        horizontal=True, key=f'yoy_mode_{current_year == today.year}',
        help="YTD = dal 1° gennaio alla data odierna, applicato a entrambi gli anni."
    )

    def _bounds(year):
        start = pd.Timestamp(year, 1, 1)
        if period_mode == "Fino a oggi (YTD)":
            try:
                end = pd.Timestamp(year, today.month, today.day)
            except Exception:
                end = pd.Timestamp(year, today.month, 28)
        else:
            end = pd.Timestamp(year, 12, 31)
        return start, end

    current_start, current_end = _bounds(current_year)
    prev_start, prev_end = _bounds(prev_year)

    curr_df = df[(df['date'] >= current_start) & (df['date'] <= current_end)]
    prev_df = df[(df['date'] >= prev_start) & (df['date'] <= prev_end)]

    if curr_df.empty and prev_df.empty:
        st.info("Nessun dato per gli anni selezionati.")
        return

    if period_mode == "Anno intero" and today.year in (current_year, prev_year):
        st.warning(f"⚠️ Il {today.year} non è ancora finito: con «Anno intero» lo confronti con un anno completo. "
                   "Per un confronto equo usa «Fino a oggi».")
    st.info(
        f"**{current_year}:** {current_start.strftime('%d/%m')} → {current_end.strftime('%d/%m/%Y')}  "
        f"|  **{prev_year}:** {prev_start.strftime('%d/%m')} → {prev_end.strftime('%d/%m/%Y')}"
    )

    def period_metrics(period_df):
        inc_df = real_income(period_df)
        exp = real_expenses(period_df)['amount'].abs().sum()
        inc = inc_df['amount'].sum()
        sal = inc_df[inc_df['category'] == 'Stipendio']['amount'].sum()
        net = inc - exp
        months = max(len(period_df['date'].dt.to_period('M').unique()), 1) if not period_df.empty else 1
        avg_exp = exp / months
        return exp, inc, net, avg_exp, sal

    curr_exp, curr_inc, curr_net, curr_avg, curr_sal = period_metrics(curr_df)
    prev_exp, prev_inc, prev_net, prev_avg, prev_sal = period_metrics(prev_df)

    def delta_str(curr, prev):
        # Mostra sia la variazione % sia quanto ammontava la voce l'anno precedente
        if prev == 0:
            return f"{prev_year}: €0"
        pct = ((curr - prev) / prev) * 100
        return f"{pct:+.1f}% · {prev_year}: €{prev:,.0f}"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(f"Spese {current_year}", f"€{curr_exp:,.0f}",
                delta=delta_str(curr_exp, prev_exp), delta_color="inverse")
    col2.metric(f"Entrate {current_year}", f"€{curr_inc:,.0f}",
                delta=delta_str(curr_inc, prev_inc))
    col3.metric(f"Risparmio Netto {current_year}", f"€{curr_net:,.0f}",
                delta=delta_str(curr_net, prev_net))
    col4.metric(f"Spesa Media/Mese {current_year}", f"€{curr_avg:,.0f}",
                delta=delta_str(curr_avg, prev_avg), delta_color="inverse")

    col5, _c6, _c7, _c8 = st.columns(4)
    col5.metric(f"Stipendio {current_year}", f"€{curr_sal:,.0f}",
                delta=delta_str(curr_sal, prev_sal))

    st.divider()

    # Monthly bar chart
    st.markdown("### 📊 Andamento Mensile")

    month_names_it = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu',
                      7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}

    def monthly_expenses_by_month(period_df, year_label):
        exp = real_expenses(period_df)
        if exp.empty:
            return pd.DataFrame()
        monthly = exp.groupby(exp['date'].dt.month)['amount'].sum().abs().reset_index()
        monthly.columns = ['month_num', 'amount']
        monthly['mese'] = monthly['month_num'].map(month_names_it)
        monthly['anno'] = str(year_label)
        return monthly

    curr_monthly = monthly_expenses_by_month(curr_df, current_year)
    prev_monthly = monthly_expenses_by_month(prev_df, prev_year)
    combined_monthly = pd.concat([curr_monthly, prev_monthly])

    if not combined_monthly.empty:
        fig = px.bar(combined_monthly, x='mese', y='amount', color='anno', barmode='group',
                     title=f"Spese Mensili: {current_year} vs {prev_year}",
                     labels={'amount': '€', 'mese': 'Mese', 'anno': 'Anno'},
                     color_discrete_map={str(current_year): '#636EFA', str(prev_year): '#EF553B'},
                     category_orders={'mese': list(month_names_it.values())})
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Stipendio mese per mese
    st.markdown("### 💼 Stipendio: Mese per Mese")
    st.markdown(
        f"Stipendio totale — **{current_year}: €{curr_sal:,.0f}** vs "
        f"**{prev_year}: €{prev_sal:,.0f}** "
        f"({'+' if curr_sal >= prev_sal else ''}€{curr_sal - prev_sal:,.0f})"
    )

    def monthly_salary_by_month(period_df, year_label):
        sal = real_income(period_df)
        sal = sal[sal['category'] == 'Stipendio']
        if sal.empty:
            return pd.DataFrame()
        monthly = sal.groupby(sal['date'].dt.month)['amount'].sum().reset_index()
        monthly.columns = ['month_num', 'amount']
        monthly['mese'] = monthly['month_num'].map(month_names_it)
        monthly['anno'] = str(year_label)
        return monthly

    curr_sal_m = monthly_salary_by_month(curr_df, current_year)
    prev_sal_m = monthly_salary_by_month(prev_df, prev_year)
    combined_sal = pd.concat([curr_sal_m, prev_sal_m])

    if not combined_sal.empty:
        fig_sal = px.bar(combined_sal, x='mese', y='amount', color='anno', barmode='group',
                         title=f"Stipendio Mensile: {current_year} vs {prev_year}",
                         labels={'amount': '€', 'mese': 'Mese', 'anno': 'Anno'},
                         color_discrete_map={str(current_year): '#00CC96', str(prev_year): '#EF553B'},
                         category_orders={'mese': list(month_names_it.values())})
        fig_sal.update_layout(height=380)
        st.plotly_chart(fig_sal, use_container_width=True)
    else:
        st.caption("Nessun dato stipendio per il confronto.")

    st.divider()

    # Category breakdown
    st.markdown("### 📂 Spese per Categoria")

    def cat_totals(period_df):
        exp = real_expenses(period_df)
        if exp.empty:
            return pd.Series(dtype=float)
        return exp.groupby('category')['amount'].sum().abs()

    curr_cats = cat_totals(curr_df)
    prev_cats = cat_totals(prev_df)
    all_cats = sorted(set(list(curr_cats.index) + list(prev_cats.index)))

    if all_cats:
        cat_df = pd.DataFrame({
            'Categoria': all_cats,
            str(current_year): [curr_cats.get(c, 0) for c in all_cats],
            str(prev_year): [prev_cats.get(c, 0) for c in all_cats],
        })
        cat_df['Δ€'] = cat_df[str(current_year)] - cat_df[str(prev_year)]
        cat_df['Δ%'] = cat_df.apply(
            lambda r: f"{((r[str(current_year)] - r[str(prev_year)]) / r[str(prev_year)] * 100):+.1f}%"
            if r[str(prev_year)] > 0 else "N/A", axis=1
        )
        cat_df = cat_df.sort_values(str(current_year), ascending=False)

        fig_cat = go.Figure()
        fig_cat.add_trace(go.Bar(name=str(current_year), x=cat_df['Categoria'],
                                  y=cat_df[str(current_year)], marker_color='#636EFA'))
        fig_cat.add_trace(go.Bar(name=str(prev_year), x=cat_df['Categoria'],
                                  y=cat_df[str(prev_year)], marker_color='#EF553B', opacity=0.75))
        fig_cat.update_layout(barmode='group', height=400,
                               title='Confronto Spese per Categoria',
                               legend=dict(orientation='h', yanchor='bottom', y=1.02))
        st.plotly_chart(fig_cat, use_container_width=True)

        display = cat_df.copy()
        display[str(current_year)] = display[str(current_year)].apply(lambda x: f"€{x:,.0f}")
        display[str(prev_year)] = display[str(prev_year)].apply(lambda x: f"€{x:,.0f}")
        display['Δ€'] = display['Δ€'].apply(lambda x: f"{'+'if x >= 0 else ''}€{x:,.0f}")
        st.dataframe(display, use_container_width=True, hide_index=True)

    # Need vs Want
    if 'necessity' in df.columns:
        st.divider()
        st.markdown("### 🎯 Need vs Want")

        def nw_totals(period_df, year_label):
            exp = real_expenses(period_df)
            if exp.empty:
                return {}
            return {
                'Anno': str(year_label),
                'Need': exp[exp['necessity'] == 'Need']['amount'].abs().sum(),
                'Want': exp[exp['necessity'] == 'Want']['amount'].abs().sum(),
            }

        curr_nw = nw_totals(curr_df, current_year)
        prev_nw = nw_totals(prev_df, prev_year)

        if curr_nw and prev_nw:
            nw_df = pd.DataFrame([curr_nw, prev_nw])
            fig_nw = px.bar(nw_df, x='Anno', y=['Need', 'Want'], barmode='group',
                            title='Need vs Want: Confronto Annuale',
                            color_discrete_map={'Need': '#EF553B', 'Want': '#636EFA'})
            fig_nw.update_layout(height=350)
            st.plotly_chart(fig_nw, use_container_width=True)
