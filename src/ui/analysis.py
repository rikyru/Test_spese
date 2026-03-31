import calendar
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from src.data_manager import DataManager


def render_analysis(data_manager: DataManager):
    st.header("Deep Analysis & Forecasting")

    df = data_manager.get_transactions()
    if df.empty:
        st.info("No data available.")
        return
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year
    df['month'] = df['date'].dt.month

    st.sidebar.subheader("Analysis Filters")
    min_date = df['date'].min().date()
    max_date = df['date'].max().date()

    filter_mode = st.sidebar.radio("Analysis Period", ["All Time", "Year", "Month", "Custom"], key='ana_filter')

    filtered_df = df.copy()

    if filter_mode == "Year":
        selected_year = st.sidebar.selectbox("Select Year", sorted(df['year'].unique(), reverse=True), key='ana_year')
        filtered_df = df[df['year'] == selected_year]
        st.info(f"Analyzing data for Year: {selected_year}")

    elif filter_mode == "Month":
        selected_year = st.sidebar.selectbox("Select Year", sorted(df['year'].unique(), reverse=True), key='ana_year_m')
        selected_month = st.sidebar.selectbox("Select Month", range(1, 13), key='ana_month')
        filtered_df = df[(df['year'] == selected_year) & (df['month'] == selected_month)]
        st.info(f"Analyzing data for: {selected_month}/{selected_year}")

    elif filter_mode == "Custom":
        start_date = st.sidebar.date_input("Start Date", min_date, key='ana_start')
        end_date = st.sidebar.date_input("End Date", max_date, key='ana_end')
        if start_date <= end_date:
            filtered_df = df[(df['date'].dt.date >= start_date) & (df['date'].dt.date <= end_date)]
            st.info(f"Analyzing from {start_date} to {end_date}")
        else:
            st.error("Start date must be before end date.")

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["Smart Insights", "Income Analysis", "Tag Analysis", "Needs vs Wants", "Forecasting", "📅 Anno vs Anno"])

    with tab1:
        render_smart_insights(df, filtered_df, data_manager)

    with tab2:
        render_income_analysis(df, filtered_df)

    with tab3:
        render_tag_analysis(filtered_df)

    with tab4:
        render_needs_vs_wants(df, filtered_df)

    with tab5:
        render_forecasting(filtered_df, df)

    with tab6:
        render_yoy_comparison(df)


# ---------------------------------------------------------------------------
# SMART INSIGHTS
# ---------------------------------------------------------------------------

def render_smart_insights(full_df, filtered_df, data_manager=None):
    st.subheader("🧠 Smart Insights")

    if filtered_df.empty:
        st.info("No data available for insights.")
        return

    full_df = full_df.copy()
    filtered_df = filtered_df.copy()
    full_df['date'] = pd.to_datetime(full_df['date'])
    filtered_df['date'] = pd.to_datetime(filtered_df['date'])

    all_expenses = full_df[full_df['type'] == 'Expense'].copy()
    all_expenses['abs_amount'] = all_expenses['amount'].abs()
    all_expenses['month_year'] = all_expenses['date'].dt.to_period('M')
    all_income = full_df[full_df['type'] == 'Income'].copy()

    expenses = filtered_df[filtered_df['type'] == 'Expense'].copy()
    expenses['abs_amount'] = expenses['amount'].abs()
    income = filtered_df[filtered_df['type'] == 'Income'].copy()

    if expenses.empty:
        st.write("No expenses to analyze.")
        return

    expenses['month_year'] = expenses['date'].dt.to_period('M')
    total_expenses = expenses['abs_amount'].sum()
    total_income = income['amount'].sum() if not income.empty else 0

    # ====== 1. BURN RATE ======
    st.markdown("### 🔥 Velocità di Spesa")

    last_month_period = expenses['month_year'].max()
    last_month_exp = expenses[expenses['month_year'] == last_month_period]

    if not last_month_exp.empty:
        # Use actual calendar days of the month, not transaction date range
        days_in_period = calendar.monthrange(last_month_period.year, last_month_period.month)[1]
        daily_burn = last_month_exp['abs_amount'].sum() / days_in_period

        prev_month_period = last_month_period - 1
        prev_month_exp = expenses[expenses['month_year'] == prev_month_period]

        col1, col2, col3 = st.columns(3)
        col1.metric("Spesa Media Giornaliera", f"€{daily_burn:,.2f}")
        col2.metric("Totale Mese Corrente", f"€{last_month_exp['abs_amount'].sum():,.2f}")

        if not prev_month_exp.empty:
            prev_days = calendar.monthrange(prev_month_period.year, prev_month_period.month)[1]
            prev_burn = prev_month_exp['abs_amount'].sum() / prev_days
            delta = daily_burn - prev_burn
            col3.metric("vs Mese Precedente", f"€{prev_burn:,.2f}/g",
                        delta=f"{delta:+.2f} €/g", delta_color="inverse")
        else:
            col3.metric("vs Mese Precedente", "N/A")

    st.divider()

    # ====== 2. MONTH OVER MONTH ======
    st.markdown("### 📊 Confronto Mese su Mese")

    all_monthly_totals = all_expenses.groupby('month_year')['abs_amount'].sum().sort_index()

    if len(all_monthly_totals) >= 2:
        # Use explicit last 2 periods from sorted index (not iloc on filtered data)
        curr_period = all_monthly_totals.index[-1]
        prev_period = all_monthly_totals.index[-2]
        curr_total = all_monthly_totals[curr_period]
        prev_total = all_monthly_totals[prev_period]
        diff = curr_total - prev_total
        pct = (diff / prev_total) * 100 if prev_total > 0 else 0

        if diff > 0:
            st.warning(f"📈 Hai speso **€{abs(diff):,.2f} in più** rispetto a {prev_period} (+{pct:.1f}%)")
        else:
            st.success(f"📉 Hai speso **€{abs(diff):,.2f} in meno** rispetto a {prev_period} ({pct:.1f}%)")

        comp_data = pd.DataFrame({
            'Mese': [str(prev_period), str(curr_period)],
            'Spese': [prev_total, curr_total]
        })
        colors = ['#636EFA', '#EF553B' if diff > 0 else '#00CC96']
        fig_comp = px.bar(comp_data, x='Mese', y='Spese', color='Mese',
                          color_discrete_sequence=colors, text_auto='.2s')
        fig_comp.update_layout(showlegend=False, height=300)
        st.plotly_chart(fig_comp, use_container_width=True)
    else:
        st.info("Servono almeno 2 mesi di dati per il confronto.")

    st.divider()

    # ====== 3. CATEGORY TRENDS ======
    st.markdown("### 📈 Trend Categorie")

    if len(all_monthly_totals) >= 3:
        last_3_months = sorted(all_expenses['month_year'].unique())[-3:]
        recent = all_expenses[all_expenses['month_year'].isin(last_3_months)]
        cat_monthly = recent.groupby(['month_year', 'category'])['abs_amount'].sum().reset_index()

        trends = []
        for cat in cat_monthly['category'].unique():
            cat_data = cat_monthly[cat_monthly['category'] == cat].sort_values('month_year')
            if len(cat_data) >= 2:
                values = cat_data['abs_amount'].values
                avg_prev = values[:-1].mean()
                last_val = values[-1]
                change_pct = ((last_val - avg_prev) / avg_prev) * 100 if avg_prev > 0 else 0

                if change_pct > 15:
                    badge = "🔴 ↑"
                elif change_pct < -15:
                    badge = "🟢 ↓"
                else:
                    badge = "⚪ →"

                trends.append({
                    'Categoria': cat,
                    'Trend': badge,
                    '_ultimo_val': last_val,
                    '_avg_val': avg_prev,
                    '_change_num': change_pct,
                    'Ultimo Mese': f"€{last_val:,.0f}",
                    'Media 2 Mesi': f"€{avg_prev:,.0f}",
                    'Variazione': f"{change_pct:+.0f}%"
                })

        if trends:
            trends_df = pd.DataFrame(trends).sort_values('_change_num', ascending=False)
            display_cols = ['Categoria', 'Trend', 'Ultimo Mese', 'Media 2 Mesi', 'Variazione']
            st.dataframe(trends_df[display_cols], use_container_width=True, hide_index=True)
    else:
        st.info("Servono almeno 3 mesi di dati per i trend.")

    st.divider()

    # ====== 4. SAVINGS RATE GAUGE ======
    st.markdown("### 💰 Tasso di Risparmio")

    savings_rate = None
    avg_monthly_sub = None
    subs = pd.DataFrame()

    if total_income > 0:
        savings = total_income - total_expenses
        savings_rate = (savings / total_income) * 100

        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=savings_rate,
            number={'suffix': '%', 'font': {'size': 40}},
            title={'text': 'Savings Rate', 'font': {'size': 18}},
            gauge={
                'axis': {'range': [-20, 60], 'ticksuffix': '%'},
                'bar': {'color': '#2196F3'},
                'steps': [
                    {'range': [-20, 10], 'color': '#FFCDD2'},
                    {'range': [10, 20], 'color': '#FFF9C4'},
                    {'range': [20, 60], 'color': '#C8E6C9'}
                ],
                'threshold': {
                    'line': {'color': '#4CAF50', 'width': 4},
                    'thickness': 0.8,
                    'value': 20
                }
            }
        ))
        fig_gauge.update_layout(height=300)

        col1, col2 = st.columns([2, 1])
        with col1:
            st.plotly_chart(fig_gauge, use_container_width=True)
        with col2:
            st.metric("Entrate Totali", f"€{total_income:,.2f}")
            st.metric("Spese Totali", f"€{total_expenses:,.2f}")
            st.metric("Risparmiato", f"€{savings:,.2f}")
            if savings_rate < 10:
                st.error("⚠️ Sotto il 10% — zona di rischio")
            elif savings_rate < 20:
                st.warning("📊 Discreto, punta al 20%+")
            else:
                st.success("🎉 Ottimo tasso di risparmio!")
    else:
        st.info("Nessun dato sulle entrate per calcolare il tasso di risparmio.")

    st.divider()

    # ====== 5. SUBSCRIPTION TRACKER ======
    st.markdown("### 🔄 Costo Abbonamenti")

    # Check both tag 'abbonamento' AND recurring expenses table
    sub_mask = filtered_df['tags'].apply(
        lambda t: any(tag in ['abbonamento', 'subscription']
                      for tag in (t if isinstance(t, list) else
                                  t.tolist() if hasattr(t, 'tolist') else []))
    )
    subs = filtered_df[sub_mask & (filtered_df['type'] == 'Expense')].copy()

    # Also pull from recurring_expenses (if data_manager available)
    rec_monthly_total = 0.0
    rec_names = []
    if data_manager is not None:
        try:
            rec_df = data_manager.get_recurring()
            if not rec_df.empty:
                def to_monthly(row):
                    amt = abs(row['amount'])
                    freq = row.get('frequency', 'Monthly')
                    if freq == 'Monthly': return amt
                    if freq == 'Yearly': return amt / 12
                    if freq == 'Weekly': return amt * 4.33
                    return amt
                rec_monthly_total = rec_df.apply(to_monthly, axis=1).sum()
                rec_names = rec_df['name'].tolist()
        except Exception:
            pass

    if not subs.empty:
        subs['abs_amount'] = subs['amount'].abs()
        subs['month_year'] = subs['date'].dt.to_period('M')
        monthly_sub_cost = subs.groupby('month_year')['abs_amount'].sum()
        avg_monthly_sub = monthly_sub_cost.mean()
        annual_proj = avg_monthly_sub * 12

        col1, col2, col3 = st.columns(3)
        col1.metric("💳 Costo Mensile Medio (Transazioni)", f"€{avg_monthly_sub:,.2f}")
        col2.metric("📅 Proiezione Annuale", f"€{annual_proj:,.2f}")
        col3.metric("Nr. Servizi Unici", str(subs['description'].nunique()))

        sub_breakdown = subs.groupby('description')['abs_amount'].agg(['sum', 'count', 'mean']).reset_index()
        sub_breakdown.columns = ['Servizio', 'Totale', 'Transazioni', 'Media']
        sub_breakdown = sub_breakdown.sort_values('Totale', ascending=False)
        sub_breakdown['Totale'] = sub_breakdown['Totale'].apply(lambda x: f"€{x:,.2f}")
        sub_breakdown['Media'] = sub_breakdown['Media'].apply(lambda x: f"€{x:,.2f}")
        st.dataframe(sub_breakdown, use_container_width=True, hide_index=True)
    else:
        st.info('Nessun abbonamento trovato con tag "abbonamento". Tagga le transazioni per tracciarle.')

    if rec_monthly_total > 0:
        st.info(f"📋 **Ricorrenti configurate:** €{rec_monthly_total:,.2f}/mese ({len(rec_names)} voci: {', '.join(rec_names[:5])}{'...' if len(rec_names) > 5 else ''})")

    st.divider()

    # ====== 6. ANNUAL PROJECTION ======
    st.markdown("### 🔮 Proiezione \"Se continui così...\"")

    if len(all_monthly_totals) >= 3:
        avg_3m_expense = all_monthly_totals.iloc[-3:].mean()
        projected_annual_expense = avg_3m_expense * 12

        if total_income > 0:
            all_income['month_year'] = all_income['date'].dt.to_period('M')
            monthly_income = all_income.groupby('month_year')['amount'].sum().sort_index()
            avg_3m_income = monthly_income.iloc[-3:].mean() if len(monthly_income) >= 3 else monthly_income.mean()
            projected_annual_income = avg_3m_income * 12
            projected_annual_savings = projected_annual_income - projected_annual_expense

            col1, col2, col3 = st.columns(3)
            col1.metric("Spesa Media (3 mesi)", f"€{avg_3m_expense:,.0f}/mese")
            col2.metric("Spesa Annuale Proiettata", f"€{projected_annual_expense:,.0f}")

            if projected_annual_savings > 0:
                col3.metric("Risparmio Annuale Stimato", f"€{projected_annual_savings:,.0f}",
                            delta=f"+€{projected_annual_savings:,.0f}", delta_color="normal")
                st.success(f"💪 A questo ritmo, a fine anno avrai risparmiato circa **€{projected_annual_savings:,.0f}**")
            else:
                col3.metric("Deficit Annuale Stimato", f"€{abs(projected_annual_savings):,.0f}",
                            delta=f"-€{abs(projected_annual_savings):,.0f}", delta_color="inverse")
                st.error(f"⚠️ A questo ritmo, a fine anno sarai in negativo di **€{abs(projected_annual_savings):,.0f}**")
        else:
            st.metric("Spesa Annuale Proiettata", f"€{projected_annual_expense:,.0f}")
    else:
        st.info("Servono almeno 3 mesi di dati per la proiezione.")

    st.divider()

    # ====== 7. WEEKDAY HEATMAP ======
    st.markdown("### 📅 Quando Spendi di Più?")

    weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    weekday_it = {'Monday': 'Lunedì', 'Tuesday': 'Martedì', 'Wednesday': 'Mercoledì',
                  'Thursday': 'Giovedì', 'Friday': 'Venerdì', 'Saturday': 'Sabato', 'Sunday': 'Domenica'}

    expenses['weekday'] = expenses['date'].dt.day_name()
    weekday_spend = expenses.groupby('weekday')['abs_amount'].agg(['sum', 'mean', 'count']).reindex(weekday_order)
    weekday_spend.index = [weekday_it.get(d, d) for d in weekday_spend.index]
    weekday_spend = weekday_spend.dropna()

    if not weekday_spend.empty:
        top_day = weekday_spend['sum'].idxmax()
        top_day_avg = weekday_spend.loc[top_day, 'mean']

        fig_heatmap = px.bar(weekday_spend.reset_index(),
                             x='index', y='mean',
                             color='mean',
                             color_continuous_scale=['#C8E6C9', '#FFF9C4', '#FFCDD2'],
                             labels={'index': 'Giorno', 'mean': 'Spesa Media (€)'},
                             title='Spesa Media per Giorno della Settimana')
        fig_heatmap.update_layout(coloraxis_showscale=False, height=350)
        st.plotly_chart(fig_heatmap, use_container_width=True)
        st.info(f"💡 Il tuo giorno più costoso è il **{top_day}** (media €{top_day_avg:,.2f} per transazione)")

    st.divider()

    # ====== 8. TOP MERCHANTS ======
    st.markdown("### 🏪 Top Spese Ricorrenti")

    merchant_stats = expenses.groupby('description').agg(
        totale=('abs_amount', 'sum'),
        conteggio=('abs_amount', 'count'),
        media=('abs_amount', 'mean')
    ).reset_index().sort_values('totale', ascending=False)

    def get_top_tags(grp):
        all_tags = []
        for tags in grp:
            if isinstance(tags, list):
                all_tags.extend(tags)
            elif hasattr(tags, 'tolist'):
                all_tags.extend(tags.tolist())
        if not all_tags:
            return ''
        from collections import Counter
        top = Counter(all_tags).most_common(3)
        return ', '.join(f'#{t}' for t, _ in top)

    tag_map = expenses.groupby('description')['tags'].apply(get_top_tags)
    merchant_stats = merchant_stats.merge(tag_map.rename('tags_str'), left_on='description', right_index=True, how='left')
    merchant_stats['tags_str'] = merchant_stats['tags_str'].fillna('')

    recurring_merchants = merchant_stats[merchant_stats['conteggio'] >= 2].head(10)

    if not recurring_merchants.empty:
        display = recurring_merchants.copy()
        display.columns = ['Descrizione', 'Totale', 'Volte', 'Media', 'Tags']
        display['Totale'] = display['Totale'].apply(lambda x: f"€{x:,.2f}")
        display['Media'] = display['Media'].apply(lambda x: f"€{x:,.2f}")
        st.dataframe(display, use_container_width=True, hide_index=True)

        top = merchant_stats.iloc[0]
        if top['conteggio'] >= 3:
            n_months = max(len(expenses['month_year'].unique()), 1)
            freq_per_month = top['conteggio'] / n_months
            st.info(f"📌 Spendi in media **€{top['media']:,.2f}** × **{freq_per_month:.1f} volte/mese** da **{top['description']}**")
    else:
        st.info("Non ci sono abbastanza dati per identificare spese ricorrenti.")

    st.divider()

    # ====== 9. ANOMALY DETECTION ======
    st.markdown("### 🚨 Spese Anomale")
    st.caption("Transazioni significativamente superiori alla media della loro categoria (> media + 2σ)")

    anomalies = []
    for cat in expenses['category'].dropna().unique():
        cat_exp = expenses[expenses['category'] == cat]
        if len(cat_exp) < 4:
            continue
        mean_val = cat_exp['abs_amount'].mean()
        std_val = cat_exp['abs_amount'].std()
        if std_val == 0:
            continue
        threshold = mean_val + 2 * std_val
        unusual = cat_exp[cat_exp['abs_amount'] > threshold]
        for _, row in unusual.iterrows():
            z_score = (row['abs_amount'] - mean_val) / std_val
            anomalies.append({
                'Data': row['date'].date(),
                'Descrizione': row['description'],
                'Categoria': cat,
                'Importo': row['abs_amount'],
                'Media Cat.': mean_val,
                '_zscore': z_score,
                'Deviazione': f"+{z_score:.1f}σ"
            })

    if anomalies:
        anom_df = pd.DataFrame(anomalies).sort_values('_zscore', ascending=False)
        display_anom = anom_df[['Data', 'Descrizione', 'Categoria', 'Importo', 'Media Cat.', 'Deviazione']].copy()
        display_anom['Importo'] = display_anom['Importo'].apply(lambda x: f"€{x:,.2f}")
        display_anom['Media Cat.'] = display_anom['Media Cat.'].apply(lambda x: f"€{x:,.2f}")
        st.dataframe(display_anom, use_container_width=True, hide_index=True)
    else:
        st.success("✅ Nessuna spesa anomala rilevata nel periodo selezionato.")

    st.divider()

    # ====== 10. PERSONALIZED TIPS ======
    st.markdown("### 💡 Consigli Personalizzati")

    tips = []

    # Tip: Restaurant spending
    if total_expenses > 0:
        try:
            cat_mask = expenses['category'].notna() & expenses['category'].str.lower().isin(['ristoranti', 'restaurants', 'cibo fuori', 'food'])
            ristoranti = expenses[cat_mask]
            if not ristoranti.empty:
                rist_pct = (ristoranti['abs_amount'].sum() / total_expenses) * 100
                if rist_pct > 15:
                    monthly_rist = ristoranti['abs_amount'].sum() / max(len(expenses['month_year'].unique()), 1)
                    potential_save = monthly_rist * 0.3
                    tips.append(f"🍕 **Ristoranti = {rist_pct:.0f}% delle spese.** Cucinando a casa 2 volte in più a settimana potresti risparmiare ~€{potential_save:,.0f}/mese.")
        except Exception:
            pass

    # Tip: Subscriptions
    if avg_monthly_sub is not None and avg_monthly_sub > 50:
        tips.append(f"📺 **Abbonamenti = €{avg_monthly_sub:,.0f}/mese.** Rivedi i servizi che usi meno — anche tagliarne uno da €10 sono €120/anno.")

    # Tip: Savings rate
    if savings_rate is not None and total_income > 0:
        if savings_rate < 10:
            tips.append("💸 **Savings rate sotto il 10%.** Prova la regola 50/30/20: 50% bisogni, 30% desideri, 20% risparmio.")
        elif savings_rate < 20:
            n_months_inc = max(len(income['date'].dt.to_period('M').unique()), 1) if not income.empty else 1
            extra_monthly = ((20 - savings_rate) / 100) * (total_income / n_months_inc)
            tips.append(f"📊 **Savings rate al {savings_rate:.0f}%.** Per arrivare al 20%, basta risparmiare €{extra_monthly:,.0f} in più al mese.")

    # Tip: Want spending
    if 'necessity' in expenses.columns:
        wants = expenses[expenses['necessity'] == 'Want']
        if not wants.empty and total_expenses > 0:
            want_pct = (wants['abs_amount'].sum() / total_expenses) * 100
            if want_pct > 35:
                cut_20 = wants['abs_amount'].sum() * 0.20 / max(len(expenses['month_year'].unique()), 1)
                tips.append(f"🛍️ **I 'Want' sono il {want_pct:.0f}% delle spese.** Tagliando il 20% delle spese non essenziali risparmi ~€{cut_20:,.0f}/mese.")

    # Tip: Weekend spending
    if not weekday_spend.empty:
        weekend_days = ['Sabato', 'Domenica']
        weekend_avg = weekday_spend.loc[weekday_spend.index.isin(weekend_days), 'mean'].mean()
        weekday_avg = weekday_spend.loc[~weekday_spend.index.isin(weekend_days), 'mean'].mean()
        if pd.notna(weekend_avg) and pd.notna(weekday_avg) and weekday_avg > 0 and weekend_avg > weekday_avg * 1.5:
            tips.append(f"🗓️ **Nel weekend spendi {weekend_avg/weekday_avg:.1f}x di più** rispetto ai giorni feriali. Pianifica attività gratuite!")

    if tips:
        for tip in tips:
            st.markdown(tip)
    else:
        st.success("🎉 Ottimo lavoro! Non ho suggerimenti particolari — stai gestendo bene le tue finanze.")


# ---------------------------------------------------------------------------
# TAG ANALYSIS
# ---------------------------------------------------------------------------

def render_tag_analysis(df):
    st.subheader("Tag Analysis")

    df_tags = df.copy().explode('tags')
    df_tags['tags'] = df_tags['tags'].astype(str)
    df_tags = df_tags[~df_tags['tags'].isin(['nan', '', 'None'])]

    if df_tags.empty:
        st.info("No tags found in data.")
        return

    all_tags = sorted(df_tags['tags'].unique())
    selected_tag = st.selectbox("Select Tag to Analyze", all_tags)

    if not selected_tag:
        return

    tag_data = df_tags[df_tags['tags'] == selected_tag].copy()
    tag_data['date'] = pd.to_datetime(tag_data['date'])

    expenses_only = tag_data[tag_data['type'] == 'Expense'].copy()
    expenses_only['abs_amount'] = expenses_only['amount'].abs()

    total_tag = expenses_only['abs_amount'].sum() if not expenses_only.empty else 0
    avg_tag = expenses_only['abs_amount'].mean() if not expenses_only.empty else 0
    count_tag = len(expenses_only)

    cols = st.columns(3)
    cols[0].metric(f"Totale Speso ({selected_tag})", f"€{total_tag:,.2f}")
    cols[1].metric("Media per Transazione", f"€{avg_tag:,.2f}")
    cols[2].metric("Numero Transazioni", str(count_tag))

    if expenses_only.empty:
        st.info("Nessuna spesa con questo tag.")
        return

    # Monthly trend
    expenses_only['month_year'] = expenses_only['date'].dt.to_period('M')
    monthly_tag = expenses_only.groupby('month_year')['abs_amount'].sum().reset_index()
    monthly_tag['month_str'] = monthly_tag['month_year'].astype(str)

    fig_trend = go.Figure()
    fig_trend.add_trace(go.Bar(
        x=monthly_tag['month_str'], y=monthly_tag['abs_amount'],
        name='Spesa mensile', marker_color='#636EFA', opacity=0.7
    ))
    if len(monthly_tag) >= 3:
        # Moving average
        monthly_tag['ma3'] = monthly_tag['abs_amount'].rolling(3, min_periods=1).mean()
        fig_trend.add_trace(go.Scatter(
            x=monthly_tag['month_str'], y=monthly_tag['ma3'],
            name='Media mobile 3m', mode='lines+markers',
            line=dict(color='#EF553B', width=2, dash='dot')
        ))
    fig_trend.update_layout(title=f"Trend Mensile — #{selected_tag}", xaxis_title="Mese",
                             yaxis_title="€", hovermode="x unified", height=350)
    st.plotly_chart(fig_trend, use_container_width=True)

    # Top transactions for this tag
    st.markdown("**Transazioni più recenti con questo tag**")
    display = expenses_only.sort_values('date', ascending=False)[['date', 'description', 'category', 'abs_amount']].head(15).copy()
    display['abs_amount'] = display['abs_amount'].apply(lambda x: f"€{x:,.2f}")
    display.columns = ['Data', 'Descrizione', 'Categoria', 'Importo']
    st.dataframe(display, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# NEEDS VS WANTS
# ---------------------------------------------------------------------------

def render_needs_vs_wants(full_df, filtered_df=None):
    st.subheader("Needs vs Wants")

    # Accept both old (single df) and new (full_df, filtered_df) signatures
    if filtered_df is None:
        filtered_df = full_df

    df = filtered_df.copy()

    if 'necessity' not in df.columns:
        st.warning("Necessity data not found. Please re-import data to apply new rules.")
        return

    df['date'] = pd.to_datetime(df['date'])
    df['month_year'] = df['date'].dt.to_period('M').astype(str)
    expenses = df[df['type'] == 'Expense'].copy()
    expenses['abs_amount'] = expenses['amount'].abs()

    if expenses.empty:
        st.info("Nessuna spesa nel periodo selezionato.")
        return

    # Stacked bar over time
    nw_grouped = expenses.groupby(['month_year', 'necessity'])['abs_amount'].sum().reset_index()
    fig_nw = px.bar(nw_grouped, x='month_year', y='abs_amount', color='necessity',
                    title="Needs vs Wants nel Tempo", barmode='stack',
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
    col1.metric("Needs", f"€{needs_total:,.2f}", f"{needs_pct:.0f}% del totale")
    col2.metric("Wants", f"€{wants_total:,.2f}", f"{wants_pct:.0f}% del totale")
    col3.metric("Totale Spese", f"€{total_exp:,.2f}")

    # 50/30/20 Rule comparison
    st.markdown("### 🎯 Regola 50/30/20")
    st.caption("Obiettivo: 50% Bisogni · 30% Desideri · 20% Risparmio")

    # Estimate income for the period
    income_df = filtered_df[filtered_df['type'] == 'Income'].copy() if filtered_df is not None else pd.DataFrame()
    total_income = income_df['amount'].sum() if not income_df.empty else 0

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
    else:
        st.info("Aggiungi dati di entrata per vedere il confronto con la regola 50/30/20.")


# ---------------------------------------------------------------------------
# FORECASTING
# ---------------------------------------------------------------------------

def render_forecasting(df, full_df=None):
    st.subheader("📈 Forecasting")

    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    monthly_totals = (df[df['type'] == 'Expense']
                      .groupby(pd.Grouper(key='date', freq='ME'))['amount']
                      .sum().abs())
    monthly_totals = monthly_totals[monthly_totals > 0]

    if len(monthly_totals) < 3:
        st.write("Servono almeno 3 mesi di dati per il forecast.")
        return

    # --- Metrics ---
    ma3 = monthly_totals.iloc[-3:].mean()
    # Weighted MA: weights 1,2,3 (more recent = higher weight)
    weights = np.array([1, 2, 3])
    wma3 = np.average(monthly_totals.iloc[-3:].values, weights=weights)
    last_val = monthly_totals.iloc[-1]

    # Linear regression over all available months
    x = np.arange(len(monthly_totals))
    y = monthly_totals.values
    coeffs = np.polyfit(x, y, 1)
    slope = coeffs[0]
    linear_pred = coeffs[0] * len(monthly_totals) + coeffs[1]
    linear_pred = max(linear_pred, 0)

    trend_dir = "📈 in crescita" if slope > 5 else ("📉 in calo" if slope < -5 else "➡️ stabile")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Ultimo Mese", f"€{last_val:,.0f}")
    col2.metric("Media Mobile 3m", f"€{ma3:,.0f}")
    col3.metric("Media Ponderata 3m", f"€{wma3:,.0f}", help="Mesi più recenti pesano di più")
    col4.metric("Regressione Lineare", f"€{linear_pred:,.0f}", help=f"Trend: {slope:+.0f} €/mese")

    st.caption(f"Trend generale: **{trend_dir}** ({slope:+.0f} €/mese)")

    # --- Chart ---
    next_month = monthly_totals.index[-1] + pd.DateOffset(months=1)

    forecast_df = monthly_totals.reset_index()
    forecast_df.columns = ['date', 'amount']
    forecast_df['type'] = 'Storico'

    # Linear regression line over historical + forecast
    x_full = np.arange(len(monthly_totals) + 1)
    linear_line = coeffs[0] * x_full + coeffs[1]
    linear_dates = list(monthly_totals.index) + [next_month]

    fig = go.Figure()

    # Historical bars
    fig.add_trace(go.Bar(
        x=forecast_df['date'], y=forecast_df['amount'],
        name='Storico', marker_color='#636EFA', opacity=0.7
    ))

    # MA3 forecast point
    fig.add_trace(go.Scatter(
        x=[next_month], y=[ma3],
        mode='markers', name='Previsione MA3',
        marker=dict(color='#00CC96', size=14, symbol='star')
    ))

    # Weighted MA forecast point
    fig.add_trace(go.Scatter(
        x=[next_month], y=[wma3],
        mode='markers', name='Previsione WMA3',
        marker=dict(color='#FFA15A', size=14, symbol='diamond')
    ))

    # Linear regression line
    fig.add_trace(go.Scatter(
        x=linear_dates, y=np.maximum(linear_line, 0),
        mode='lines', name='Trend Lineare',
        line=dict(color='#EF553B', width=2, dash='dot')
    ))

    # Confidence band (±1 std of last 3 months)
    std3 = monthly_totals.iloc[-3:].std()
    fig.add_trace(go.Scatter(
        x=[next_month, next_month],
        y=[max(ma3 - std3, 0), ma3 + std3],
        mode='lines', name='Range ±1σ',
        line=dict(color='rgba(0,204,150,0.3)', width=0),
        fill='toself', fillcolor='rgba(0,204,150,0.15)',
        showlegend=True
    ))

    fig.update_layout(
        title="Previsione Spese — Prossimo Mese",
        xaxis_title="Mese", yaxis_title="€",
        hovermode="x unified", height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig, use_container_width=True)

    # --- Per-Category Forecast ---
    st.markdown("### 📂 Previsione per Categoria")

    cat_monthly = (df[df['type'] == 'Expense']
                   .groupby([pd.Grouper(key='date', freq='ME'), 'category'])['amount']
                   .sum().abs().reset_index())
    cat_monthly.columns = ['date', 'category', 'amount']

    cat_forecasts = []
    for cat in cat_monthly['category'].dropna().unique():
        cat_data = cat_monthly[cat_monthly['category'] == cat].sort_values('date')
        if len(cat_data) < 2:
            continue
        vals = cat_data['amount'].values
        pred = np.average(vals[-3:], weights=np.array([1, 2, 3])[:len(vals[-3:])]) if len(vals) >= 2 else vals[-1]
        prev = vals[-1]
        delta = pred - prev
        cat_forecasts.append({
            'Categoria': cat,
            'Ultimo Mese': f"€{prev:,.0f}",
            'Previsione': f"€{pred:,.0f}",
            '_delta': delta,
            'Variazione': f"{'+' if delta >= 0 else ''}€{delta:,.0f}",
            'Trend': '📈' if delta > 5 else ('📉' if delta < -5 else '➡️')
        })

    if cat_forecasts:
        cf_df = pd.DataFrame(cat_forecasts).sort_values('_delta', ascending=False)
        st.dataframe(cf_df[['Categoria', 'Ultimo Mese', 'Previsione', 'Variazione', 'Trend']],
                     use_container_width=True, hide_index=True)

    # --- Scenario Fine Anno ---
    if full_df is not None:
        render_year_scenario(full_df)


# ---------------------------------------------------------------------------
# SCENARIO FINE ANNO
# ---------------------------------------------------------------------------

def render_year_scenario(full_df):
    from datetime import date as date_type
    st.divider()
    st.subheader("🎯 Scenario Fine Anno")

    today = date_type.today()
    current_year = today.year

    df = full_df.copy()
    df['date'] = pd.to_datetime(df['date'])

    ytd = df[(df['date'].dt.year == current_year) & (df['date'].dt.date <= today)]

    if ytd.empty:
        st.info(f"Nessun dato disponibile per il {current_year}.")
        return

    months_elapsed = max(len(ytd['date'].dt.to_period('M').unique()), 1)
    remaining_months = 12 - today.month  # mesi interi rimanenti dopo questo mese

    ytd_income = ytd[ytd['type'] == 'Income']['amount'].sum()
    ytd_needs = ytd[(ytd['type'] == 'Expense') & (ytd['necessity'] == 'Need')]['amount'].abs().sum()
    ytd_wants = ytd[(ytd['type'] == 'Expense') & (ytd['necessity'] == 'Want')]['amount'].abs().sum()
    ytd_other_exp = ytd[(ytd['type'] == 'Expense') & (~ytd['necessity'].isin(['Need', 'Want']))]['amount'].abs().sum()

    avg_income = ytd_income / months_elapsed
    avg_needs = ytd_needs / months_elapsed
    avg_wants = ytd_wants / months_elapsed

    # Quanto manca nel mese corrente (frazione del mese rimanente)
    days_in_month = (pd.Timestamp(today.year, today.month, 1) + pd.DateOffset(months=1) - pd.Timestamp(today.year, today.month, 1)).days
    days_elapsed_this_month = today.day
    month_fraction_remaining = (days_in_month - days_elapsed_this_month) / days_in_month

    # Proiezione: mesi rimanenti completi + resto del mese corrente
    proj_months = remaining_months + month_fraction_remaining

    proj_income = avg_income * proj_months
    proj_needs = avg_needs * proj_months
    proj_wants_base = avg_wants * proj_months

    ytd_net = ytd_income - ytd_needs - ytd_wants - ytd_other_exp
    proj_net_base = proj_income - proj_needs - proj_wants_base
    fy_net_base = ytd_net + proj_net_base

    st.caption(f"Basato su {months_elapsed} mesi di dati YTD ({current_year}). Proiezione per i restanti {remaining_months} mesi completi + {int(month_fraction_remaining * 100)}% del mese corrente.")

    col1, col2, col3 = st.columns(3)
    col1.metric("Entrata Media/Mese (YTD)", f"€{avg_income:,.0f}")
    col2.metric("Need Media/Mese (YTD)", f"€{avg_needs:,.0f}")
    col3.metric("Want Media/Mese (YTD)", f"€{avg_wants:,.0f}")

    st.divider()

    # Scenario builder
    st.markdown("### ➕ Aggiungi Spese Straordinarie")
    st.caption("Simula spese una-tantum per vedere l'impatto a fine anno (es. vacanze, regalo matrimonio, acquisto device...)")

    if 'year_scenarios' not in st.session_state:
        st.session_state['year_scenarios'] = []

    future_months = [pd.Timestamp(current_year, m, 1).strftime('%B %Y')
                     for m in range(today.month, 13)]
    future_month_nums = list(range(today.month, 13))

    with st.form("scenario_add_form", clear_on_submit=True):
        col_a, col_b, col_c = st.columns([3, 2, 2])
        sc_name = col_a.text_input("Descrizione", placeholder="es. Regalo matrimonio")
        sc_amount = col_b.number_input("Importo €", min_value=0.0, step=10.0)
        sc_month_label = col_c.selectbox("Mese", future_months)
        if st.form_submit_button("➕ Aggiungi", use_container_width=False):
            if sc_name and sc_amount > 0:
                sc_month_num = future_month_nums[future_months.index(sc_month_label)]
                st.session_state['year_scenarios'].append({
                    'nome': sc_name,
                    'importo': sc_amount,
                    'mese': sc_month_num,
                    'mese_label': sc_month_label
                })
                st.rerun()

    if st.session_state['year_scenarios']:
        st.markdown("**Spese aggiunte:**")
        for i, sc in enumerate(st.session_state['year_scenarios']):
            col_x, col_y = st.columns([5, 1])
            col_x.markdown(f"- **{sc['nome']}** — €{sc['importo']:,.0f} ({sc['mese_label']})")
            if col_y.button("🗑️", key=f"del_sc_{i}"):
                st.session_state['year_scenarios'].pop(i)
                st.rerun()

        total_extra = sum(sc['importo'] for sc in st.session_state['year_scenarios'])
        fy_net_scenario = fy_net_base - total_extra

        st.divider()
        st.markdown("### 📊 Risultato Simulazione")
        col1, col2, col3 = st.columns(3)
        col1.metric("Risparmio Fine Anno (Baseline)", f"€{fy_net_base:,.0f}",
                    delta_color="normal")
        col2.metric("Spese Extra Totali", f"€{total_extra:,.0f}",
                    delta=f"-€{total_extra:,.0f}", delta_color="inverse")
        col3.metric("Risparmio Fine Anno (Scenario)", f"€{fy_net_scenario:,.0f}",
                    delta=f"€{fy_net_scenario - fy_net_base:,.0f}", delta_color="normal")

        if fy_net_scenario < 0:
            st.error(f"⚠️ Con queste spese extra andresti in rosso di €{abs(fy_net_scenario):,.0f} a fine anno.")
        elif fy_net_scenario < fy_net_base * 0.5:
            st.warning(f"📉 Le spese extra dimezzano quasi il risparmio previsto.")
        else:
            st.success(f"✅ Puoi permetterti queste spese mantenendo un risparmio di €{fy_net_scenario:,.0f}.")
    else:
        st.divider()
        st.markdown("### 📊 Proiezione Baseline")
        col1, col2, col3 = st.columns(3)
        col1.metric("Entrate Proiettate (resto anno)", f"€{proj_income:,.0f}")
        col2.metric("Spese Proiettate (resto anno)", f"€{proj_needs + proj_wants_base:,.0f}")
        col3.metric("Risparmio Stimato Fine Anno", f"€{fy_net_base:,.0f}",
                    delta_color="normal")
        if fy_net_base > 0:
            st.success(f"🎯 A questo ritmo finirai l'anno con un risparmio netto di **€{fy_net_base:,.0f}**.")
        else:
            st.error(f"⚠️ A questo ritmo finirai l'anno con un deficit di **€{abs(fy_net_base):,.0f}**.")

    # Chart mensile proiezione
    st.divider()
    st.markdown("### 📈 Cashflow Mensile Proiettato")

    chart_rows = []
    month_names_it = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu',
                      7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}

    # Mesi passati (YTD)
    for m in range(1, today.month + 1):
        m_df = ytd[ytd['date'].dt.month == m]
        inc = m_df[m_df['type'] == 'Income']['amount'].sum()
        exp = m_df[m_df['type'] == 'Expense']['amount'].abs().sum()
        chart_rows.append({'mese': month_names_it[m], 'num': m,
                           'entrate': inc, 'spese': exp,
                           'tipo': 'Storico'})

    # Mesi futuri (proiezione)
    extra_by_month = {}
    for sc in st.session_state.get('year_scenarios', []):
        extra_by_month[sc['mese']] = extra_by_month.get(sc['mese'], 0) + sc['importo']

    for m in range(today.month + 1, 13):
        extra = extra_by_month.get(m, 0)
        chart_rows.append({'mese': month_names_it[m], 'num': m,
                           'entrate': avg_income,
                           'spese': avg_needs + avg_wants + extra,
                           'tipo': 'Proiezione' if extra == 0 else 'Proiezione + Extra'})

    chart_df = pd.DataFrame(chart_rows)
    chart_df['netto'] = chart_df['entrate'] - chart_df['spese']

    fig = go.Figure()
    colors = {'Storico': '#636EFA', 'Proiezione': '#00CC96', 'Proiezione + Extra': '#FFA15A'}
    for tipo in chart_df['tipo'].unique():
        sub = chart_df[chart_df['tipo'] == tipo]
        fig.add_trace(go.Bar(x=sub['mese'], y=sub['netto'], name=tipo,
                             marker_color=colors.get(tipo, '#AAAAAA')))

    fig.add_trace(go.Scatter(x=chart_df['mese'], y=chart_df['netto'].cumsum(),
                             mode='lines+markers', name='Cumulativo',
                             line=dict(color='white', width=2, dash='dot'),
                             yaxis='y2'))

    fig.update_layout(
        title="Netto Mensile (Storico + Proiezione)",
        barmode='relative',
        height=420,
        yaxis=dict(title='Netto €'),
        yaxis2=dict(title='Cumulativo €', overlaying='y', side='right', showgrid=False),
        legend=dict(orientation='h', yanchor='bottom', y=1.02),
        hovermode='x unified'
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# INCOME ANALYSIS
# ---------------------------------------------------------------------------

def render_income_analysis(full_df, filtered_df):
    st.subheader("💰 Income Analysis")

    full_income = full_df[full_df['type'] == 'Income'].copy()
    full_income['date'] = pd.to_datetime(full_income['date'])

    if full_income.empty:
        st.info("No income data found.")
        return

    monthly_inc_all = full_income.groupby(pd.Grouper(key='date', freq='ME'))['amount'].sum()
    avg_monthly_all = monthly_inc_all.mean()

    filtered_income = filtered_df[filtered_df['type'] == 'Income'].copy()
    total_period = filtered_income['amount'].sum()

    col1, col2, col3 = st.columns(3)
    col1.metric("Avg Monthly Income (All Time)", f"€{avg_monthly_all:,.2f}")
    col2.metric("Total Income (Selected Period)", f"€{total_period:,.2f}")

    # Annual Growth Rate
    st.markdown("### 📈 Growth & Trends")
    annual_inc = full_income.groupby(full_income['date'].dt.year)['amount'].sum()

    selected_years = filtered_df['date'].dt.year.unique() if not filtered_df.empty else []
    target_year = None
    if len(selected_years) == 1:
        target_year = selected_years[0]
    elif not annual_inc.empty:
        target_year = annual_inc.index.max()

    if target_year and (target_year - 1) in annual_inc.index:
        current_val = annual_inc[target_year]
        prev_val = annual_inc[target_year - 1]
        growth_pct = ((current_val - prev_val) / prev_val) * 100
        col3.metric(f"Growth ({target_year - 1} vs {target_year})", f"{growth_pct:+.1f}%")
    else:
        col3.info(f"Dati anno precedente non disponibili.")

    fig_annual = px.bar(x=annual_inc.index, y=annual_inc.values,
                        title="Annual Income Trend", labels={'x': 'Year', 'y': 'Total Income'})
    st.plotly_chart(fig_annual, use_container_width=True)

    st.divider()

    st.markdown("### 🏦 Income Sources")
    if not filtered_income.empty:
        filtered_income['date'] = pd.to_datetime(filtered_income['date'])
        inc_by_cat = filtered_income.groupby('category')['amount'].sum().reset_index()
        fig_pie = px.pie(inc_by_cat, values='amount', names='category',
                         title="Income Mix (Selected Period)", hole=0.4)

        monthly_cat = filtered_income.groupby([pd.Grouper(key='date', freq='ME'), 'category'])['amount'].sum().reset_index()
        fig_stack = px.bar(monthly_cat, x='date', y='amount', color='category',
                           title="Income Sources over Time")

        c1, c2 = st.columns(2)
        c1.plotly_chart(fig_pie, use_container_width=True)
        c2.plotly_chart(fig_stack, use_container_width=True)


# ---------------------------------------------------------------------------
# YOY COMPARISON
# ---------------------------------------------------------------------------

def render_yoy_comparison(full_df):
    from datetime import date as date_type
    st.subheader("📅 Confronto Anno vs Anno")

    today = date_type.today()
    current_year = today.year
    prev_year = current_year - 1

    df = full_df.copy()
    df['date'] = pd.to_datetime(df['date'])

    current_start = pd.Timestamp(current_year, 1, 1)
    current_end = pd.Timestamp(today)
    prev_start = pd.Timestamp(prev_year, 1, 1)
    try:
        prev_end = pd.Timestamp(prev_year, today.month, today.day)
    except Exception:
        prev_end = pd.Timestamp(prev_year, today.month, 28)

    curr_df = df[(df['date'] >= current_start) & (df['date'] <= current_end)]
    prev_df = df[(df['date'] >= prev_start) & (df['date'] <= prev_end)]

    if curr_df.empty and prev_df.empty:
        st.info("Dati insufficienti per il confronto anno su anno.")
        return

    st.info(
        f"**{current_year}:** {current_start.strftime('%d/%m')} → {current_end.strftime('%d/%m/%Y')}  "
        f"|  **{prev_year}:** {prev_start.strftime('%d/%m')} → {prev_end.strftime('%d/%m/%Y')}"
    )

    def period_metrics(period_df):
        exp = period_df[period_df['type'] == 'Expense']['amount'].abs().sum()
        inc = period_df[period_df['type'] == 'Income']['amount'].sum()
        net = inc - exp
        months = max(len(period_df['date'].dt.to_period('M').unique()), 1)
        avg_exp = exp / months
        return exp, inc, net, avg_exp

    curr_exp, curr_inc, curr_net, curr_avg = period_metrics(curr_df)
    prev_exp, prev_inc, prev_net, prev_avg = period_metrics(prev_df)

    def delta_str(curr, prev, inverse=False):
        if prev == 0:
            return None
        pct = ((curr - prev) / prev) * 100
        return f"{pct:+.1f}% vs {prev_year}"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(f"Spese {current_year}", f"€{curr_exp:,.0f}",
                delta=delta_str(curr_exp, prev_exp), delta_color="inverse")
    col2.metric(f"Entrate {current_year}", f"€{curr_inc:,.0f}",
                delta=delta_str(curr_inc, prev_inc))
    col3.metric(f"Risparmio Netto {current_year}", f"€{curr_net:,.0f}",
                delta=delta_str(curr_net, prev_net))
    col4.metric(f"Spesa Media/Mese {current_year}", f"€{curr_avg:,.0f}",
                delta=delta_str(curr_avg, prev_avg), delta_color="inverse")

    st.divider()

    # Monthly bar chart
    st.markdown("### 📊 Andamento Mensile")

    month_names_it = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu',
                      7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}

    def monthly_expenses_by_month(period_df, year_label):
        exp = period_df[period_df['type'] == 'Expense'].copy()
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

    # Category breakdown
    st.markdown("### 📂 Spese per Categoria")

    def cat_totals(period_df):
        exp = period_df[period_df['type'] == 'Expense'].copy()
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
            exp = period_df[period_df['type'] == 'Expense'].copy()
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
