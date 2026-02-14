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

    # Sidebar Filters
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

    # Tabs for different analysis views
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Smart Insights", "Income Analysis", "Tag Analysis", "Needs vs Wants", "Forecasting"])
    
    with tab1:
        render_smart_insights(filtered_df)

    with tab2:
        # Pass full df for historical context (Growth Rate), filtered_df for deep dive
        render_income_analysis(df, filtered_df)
        
    with tab3:
        render_tag_analysis(filtered_df)
        
    with tab4:
        render_needs_vs_wants(filtered_df)
        
    with tab5:
        # Forecasting usually needs more context than a small slice, 
        # but let's pass filtered_df. Users might select a year and want to see forecast at end of it.
        # Or better: Forecasting normally looks at LATEST data. 
        # If user selects "2020", forecasting "Next Month" (Jan 2021) is technically correct for that snapshot.
        render_forecasting(filtered_df)

def render_smart_insights(df):
    st.subheader("🧠 Smart Insights")
    
    if df.empty:
        st.info("No data available for insights.")
        return

    df['date'] = pd.to_datetime(df['date'])
    expenses = df[df['type'] == 'Expense'].copy()
    expenses['abs_amount'] = expenses['amount'].abs()
    income = df[df['type'] == 'Income'].copy()

    if expenses.empty:
        st.write("No expenses to analyze.")
        return

    expenses['month_year'] = expenses['date'].dt.to_period('M')
    
    # ========== 1. BURN RATE ==========
    st.markdown("### 🔥 Velocità di Spesa")
    
    last_month_period = expenses['month_year'].max()
    last_month_exp = expenses[expenses['month_year'] == last_month_period]
    
    if not last_month_exp.empty:
        days_in_period = (last_month_exp['date'].max() - last_month_exp['date'].min()).days + 1
        days_in_period = max(days_in_period, 1)
        daily_burn = last_month_exp['abs_amount'].sum() / days_in_period
        
        # Previous month for comparison
        prev_month_period = last_month_period - 1
        prev_month_exp = expenses[expenses['month_year'] == prev_month_period]
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Spesa Media Giornaliera", f"€{daily_burn:,.2f}")
        col2.metric("Totale Mese Corrente", f"€{last_month_exp['abs_amount'].sum():,.2f}")
        
        if not prev_month_exp.empty:
            prev_days = (prev_month_exp['date'].max() - prev_month_exp['date'].min()).days + 1
            prev_days = max(prev_days, 1)
            prev_burn = prev_month_exp['abs_amount'].sum() / prev_days
            delta = daily_burn - prev_burn
            col3.metric("vs Mese Precedente", f"€{prev_burn:,.2f}/g", 
                       delta=f"{delta:+.2f} €/g", delta_color="inverse")
        else:
            col3.metric("vs Mese Precedente", "N/A")
    
    st.divider()
    
    # ========== 2. MONTH OVER MONTH COMPARISON ==========
    st.markdown("### 📊 Confronto Mese su Mese")
    
    monthly_totals = expenses.groupby('month_year')['abs_amount'].sum()
    
    if len(monthly_totals) >= 2:
        curr_total = monthly_totals.iloc[-1]
        prev_total = monthly_totals.iloc[-2]
        diff = curr_total - prev_total
        pct = (diff / prev_total) * 100 if prev_total > 0 else 0
        
        curr_label = str(monthly_totals.index[-1])
        prev_label = str(monthly_totals.index[-2])
        
        if diff > 0:
            st.warning(f"📈 Hai speso **€{abs(diff):,.2f} in più** rispetto a {prev_label} (+{pct:.1f}%)")
        else:
            st.success(f"📉 Hai speso **€{abs(diff):,.2f} in meno** rispetto a {prev_label} ({pct:.1f}%)")
        
        # Mini bar comparison
        comp_data = pd.DataFrame({
            'Mese': [prev_label, curr_label],
            'Spese': [prev_total, curr_total]
        })
        colors = ['#636EFA', '#EF553B' if diff > 0 else '#00CC96']
        fig_comp = px.bar(comp_data, x='Mese', y='Spese', color='Mese',
                         color_discrete_sequence=colors,
                         text_auto='.2s')
        fig_comp.update_layout(showlegend=False, height=300)
        st.plotly_chart(fig_comp, use_container_width=True)
    else:
        st.info("Servono almeno 2 mesi di dati per il confronto.")
    
    st.divider()
    
    # ========== 3. CATEGORY TRENDS (Rising / Falling) ==========
    st.markdown("### 📈 Trend Categorie")
    
    if len(monthly_totals) >= 3:
        last_3_months = sorted(expenses['month_year'].unique())[-3:]
        recent = expenses[expenses['month_year'].isin(last_3_months)]
        cat_monthly = recent.groupby(['month_year', 'category'])['abs_amount'].sum().reset_index()
        
        trends = []
        for cat in cat_monthly['category'].unique():
            cat_data = cat_monthly[cat_monthly['category'] == cat].sort_values('month_year')
            if len(cat_data) >= 2:
                values = cat_data['abs_amount'].values
                # Simple trend: compare last to average of previous
                avg_prev = values[:-1].mean()
                last_val = values[-1]
                if avg_prev > 0:
                    change_pct = ((last_val - avg_prev) / avg_prev) * 100
                else:
                    change_pct = 0
                
                if change_pct > 15:
                    badge = "🔴 ↑"
                elif change_pct < -15:
                    badge = "🟢 ↓"
                else:
                    badge = "⚪ →"
                
                trends.append({
                    'Categoria': cat,
                    'Trend': badge,
                    'Ultimo Mese': f"€{last_val:,.0f}",
                    'Media': f"€{avg_prev:,.0f}",
                    'Variazione': f"{change_pct:+.0f}%"
                })
        
        if trends:
            trends_df = pd.DataFrame(trends).sort_values('Variazione', ascending=False)
            st.dataframe(trends_df, use_container_width=True, hide_index=True)
    else:
        st.info("Servono almeno 3 mesi di dati per i trend.")
    
    st.divider()
    
    # ========== 4. SAVINGS RATE GAUGE ==========
    st.markdown("### 💰 Tasso di Risparmio")
    
    total_income = income['amount'].sum() if not income.empty else 0
    total_expenses = expenses['abs_amount'].sum()
    
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
    
    # ========== 5. SUBSCRIPTION TRACKER ==========
    st.markdown("### 🔄 Costo Abbonamenti")
    
    # Find transactions with 'abbonamento' tag
    sub_mask = df['tags'].apply(
        lambda t: 'abbonamento' in (t if isinstance(t, list) else 
                                     t.tolist() if hasattr(t, 'tolist') else [])
    )
    subs = df[sub_mask & (df['type'] == 'Expense')].copy()
    
    if not subs.empty:
        subs['abs_amount'] = subs['amount'].abs()
        subs['month_year'] = subs['date'].dt.to_period('M')
        
        # Monthly average cost of subscriptions
        monthly_sub_cost = subs.groupby('month_year')['abs_amount'].sum()
        avg_monthly_sub = monthly_sub_cost.mean()
        annual_proj = avg_monthly_sub * 12
        
        col1, col2, col3 = st.columns(3)
        col1.metric("💳 Costo Mensile Medio", f"€{avg_monthly_sub:,.2f}")
        col2.metric("📅 Proiezione Annuale", f"€{annual_proj:,.2f}")
        col3.metric("Nr. Abbonamenti", str(subs['description'].nunique()))
        
        # Breakdown by description
        sub_breakdown = subs.groupby('description')['abs_amount'].agg(['sum', 'count', 'mean']).reset_index()
        sub_breakdown.columns = ['Servizio', 'Totale', 'Transazioni', 'Media']
        sub_breakdown = sub_breakdown.sort_values('Totale', ascending=False)
        sub_breakdown['Totale'] = sub_breakdown['Totale'].apply(lambda x: f"€{x:,.2f}")
        sub_breakdown['Media'] = sub_breakdown['Media'].apply(lambda x: f"€{x:,.2f}")
        st.dataframe(sub_breakdown, use_container_width=True, hide_index=True)
    else:
        st.info('Nessun abbonamento trovato. Tagga le transazioni con "abbonamento" per tracciarli.')
    
    st.divider()
    
    # ========== 6. ANNUAL PROJECTION ==========
    st.markdown("### 🔮 Proiezione \"Se continui così...\"")
    
    if len(monthly_totals) >= 3:
        avg_3m_expense = monthly_totals.iloc[-3:].mean()
        projected_annual_expense = avg_3m_expense * 12
        
        if total_income > 0:
            # Annualize income similarly
            income['month_year'] = income['date'].dt.to_period('M')
            monthly_income = income.groupby('month_year')['amount'].sum()
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
    
    # ========== 7. WEEKDAY HEATMAP ==========
    st.markdown("### 📅 Quando Spendi di Più?")
    
    expenses['weekday'] = expenses['date'].dt.day_name()
    weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    weekday_it = {'Monday': 'Lunedì', 'Tuesday': 'Martedì', 'Wednesday': 'Mercoledì', 
                  'Thursday': 'Giovedì', 'Friday': 'Venerdì', 'Saturday': 'Sabato', 'Sunday': 'Domenica'}
    
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
    
    # ========== 8. TOP MERCHANTS ==========
    st.markdown("### 🏪 Top Spese Ricorrenti")
    
    merchant_stats = expenses.groupby('description').agg(
        totale=('abs_amount', 'sum'),
        conteggio=('abs_amount', 'count'),
        media=('abs_amount', 'mean')
    ).reset_index().sort_values('totale', ascending=False)
    
    # Filter to meaningful merchants (at least 2 transactions)
    recurring_merchants = merchant_stats[merchant_stats['conteggio'] >= 2].head(10)
    
    if not recurring_merchants.empty:
        recurring_merchants_display = recurring_merchants.copy()
        recurring_merchants_display.columns = ['Descrizione', 'Totale', 'Volte', 'Media']
        recurring_merchants_display['Totale'] = recurring_merchants_display['Totale'].apply(lambda x: f"€{x:,.2f}")
        recurring_merchants_display['Media'] = recurring_merchants_display['Media'].apply(lambda x: f"€{x:,.2f}")
        st.dataframe(recurring_merchants_display, use_container_width=True, hide_index=True)
        
        top = merchant_stats.iloc[0]
        if top['conteggio'] >= 3:
            # Calculate monthly frequency
            n_months = len(expenses['month_year'].unique())
            freq_per_month = top['conteggio'] / max(n_months, 1)
            st.info(f"📌 Spendi in media **€{top['media']:,.2f}** × **{freq_per_month:.1f} volte/mese** da **{top['description']}**")
    else:
        st.info("Non ci sono abbastanza dati per identificare spese ricorrenti.")
    
    st.divider()
    
    # ========== 9. PERSONALIZED TIPS ==========
    st.markdown("### 💡 Consigli Personalizzati")
    
    tips = []
    
    # Tip: Restaurant spending
    if total_expenses > 0:
        try:
            cat_mask = expenses['category'].notna() & expenses['category'].str.lower().isin(['ristoranti', 'restaurants'])
            ristoranti = expenses[cat_mask]
            if not ristoranti.empty:
                rist_pct = (ristoranti['abs_amount'].sum() / total_expenses) * 100
                if rist_pct > 15:
                    monthly_rist = ristoranti['abs_amount'].sum() / max(len(expenses['month_year'].unique()), 1)
                    potential_save = monthly_rist * 0.3
                    tips.append(f"🍕 **Ristoranti = {rist_pct:.0f}% delle spese.** Cucinando a casa 2 volte in più a settimana potresti risparmiare ~€{potential_save:,.0f}/mese.")
        except Exception:
            pass
    
    # Tip: Subscriptions (safe check — subs/avg_monthly_sub defined in section 5)
    try:
        if not subs.empty and avg_monthly_sub > 50:
            tips.append(f"📺 **Abbonamenti = €{avg_monthly_sub:,.0f}/mese.** Rivedi i servizi che usi meno — anche tagliarne uno da €10 sono €120/anno.")
    except NameError:
        pass
    
    # Tip: Savings rate (safe check — savings_rate defined in section 4)
    try:
        if total_income > 0 and savings_rate is not None:
            if savings_rate < 10:
                tips.append("💸 **Savings rate sotto il 10%.** Prova la regola 50/30/20: 50% bisogni, 30% desideri, 20% risparmio.")
            elif savings_rate < 20:
                gap = 20 - savings_rate
                extra_monthly = (gap / 100) * (total_income / max(len(income['date'].dt.to_period('M').unique()), 1))
                tips.append(f"📊 **Savings rate al {savings_rate:.0f}%.** Per arrivare al 20%, basta risparmiare €{extra_monthly:,.0f} in più al mese.")
    except NameError:
        pass
    
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
        if weekend_avg > weekday_avg * 1.5:
            tips.append(f"🗓️ **Nel weekend spendi {weekend_avg/weekday_avg:.1f}x di più** rispetto ai giorni feriali. Pianifica attività gratuite!")
    
    if tips:
        for tip in tips:
            st.markdown(tip)
    else:
        st.success("🎉 Ottimo lavoro! Non ho suggerimenti particolari — stai gestendo bene le tue finanze.")

def render_tag_analysis(df):
    st.subheader("Tag Analysis")
    # ... (rest of tag analysis code)
    # Explode tags
    df_transactions = df.copy() # Use copy for operations
    df_tags = df_transactions.explode('tags')
    # Filter empty tags: handle list/array/string
    # Ensure tags are strings
    df_tags['tags'] = df_tags['tags'].astype(str)
    df_tags = df_tags[df_tags['tags'] != 'nan']
    df_tags = df_tags[df_tags['tags'] != '']
    df_tags = df_tags[df_tags['tags'] != 'None'] 
    
    if not df_tags.empty:
        all_tags = sorted(df_tags['tags'].unique())
        selected_tag = st.selectbox("Select Tag to Analyze", all_tags)
        
        if selected_tag:
            tag_data = df_tags[df_tags['tags'] == selected_tag]
            
            # Metrics
            total_tag = tag_data['amount'].sum()
            avg_tag = tag_data['amount'].mean()
            count_tag = len(tag_data)
            
            cols = st.columns(3)
            cols[0].metric(f"Total {selected_tag}", f"€{total_tag:,.2f}")
            cols[1].metric("Average", f"€{avg_tag:,.2f}")
            cols[2].metric("Count", str(count_tag))
            
            # Chart
            fig_tag = px.bar(tag_data, x='date', y='amount', title=f"Spending history for {selected_tag}")
            st.plotly_chart(fig_tag, use_container_width=True)
    else:
        st.info("No tags found in data.")

def render_needs_vs_wants(df):
    st.subheader("Needs vs Wants")
    if 'necessity' in df.columns:
        # Group by Month and Necessity
        # Ensure date is datetime
        df['date'] = pd.to_datetime(df['date'])
        # Use ME instead of M for future warning fix
        df['month_year'] = df['date'].dt.to_period('M').astype(str)
        # Filter Expenses only
        expenses = df[df['type'] == 'Expense'].copy()
        expenses['abs_amount'] = expenses['amount'].abs()
        
        nw_grouped = expenses.groupby(['month_year', 'necessity'])['abs_amount'].sum().reset_index()
        
        fig_nw = px.bar(nw_grouped, x='month_year', y='abs_amount', color='necessity', 
                        title="Needs vs Wants over Time", barmode='stack',
                        category_orders={"necessity": ["Need", "Want"]})
        st.plotly_chart(fig_nw, use_container_width=True)
    else:
        st.warning("Necessity data not found. Please re-import data to apply new rules.")

def render_forecasting(df):
    st.subheader("Forecasting (Simple Moving Average)")
    
    # Calculate monthly totals
    # Use ME alias for compatibility if pandas is new, or M if older. 
    # Let's try 'ME' as suggested by warnings, or suppress warning.
    # Grouping key must be datetime
    df['date'] = pd.to_datetime(df['date'])
    monthly_totals = df[df['type'] == 'Expense'].groupby(pd.Grouper(key='date', freq='ME'))['amount'].sum().abs()
    
    if len(monthly_totals) >= 3:
        last_3_avg = monthly_totals.iloc[-3:].mean()
        last_month_val = monthly_totals.iloc[-1]
        
        st.metric("3-Month Average Expense", f"€{last_3_avg:,.2f}")
        st.metric("Last Month Expense", f"€{last_month_val:,.2f}")
        
        prediction = last_3_avg
        st.info(f"Predicted Expense for Next Month: €{prediction:,.2f}")
        
        # Chart with prediction
        forecast_df = monthly_totals.reset_index()
        forecast_df.columns = ['date', 'amount']
        
        # Add next month
        next_month = forecast_df['date'].iloc[-1] + pd.DateOffset(months=1)
        new_row = pd.DataFrame({'date': [next_month], 'amount': [prediction], 'type': ['Forecast']})
        forecast_df['type'] = 'Actual'
        
        combined = pd.concat([forecast_df, new_row], ignore_index=True)
        
        fig_forecast = px.line(combined, x='date', y='amount', color='type', markers=True, title="Expense Forecast")
        st.plotly_chart(fig_forecast, use_container_width=True)
        
    else:
        st.write("Not enough data for forecasting (need at least 3 months).")

def render_income_analysis(full_df, filtered_df):
    st.subheader("💰 Income Analysis")
    
    # Use full data for trends
    full_income = full_df[full_df['type'] == 'Income'].copy()
    
    if full_income.empty:
        st.info("No income data found.")
        return

    # 1. Monthly Average (All Time vs Selected Period)
    # Use grouped by ME if newer pandas, or M if older and you want to suppress warnings or just stick to what works.
    # The warning said 'M' is deprecated, use 'ME'.
    monthly_inc_all = full_income.groupby(pd.Grouper(key='date', freq='ME'))['amount'].sum()
    avg_monthly_all = monthly_inc_all.mean()
    
    # Filtered stats
    filtered_income = filtered_df[filtered_df['type'] == 'Income']
    total_period = filtered_income['amount'].sum()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Avg Monthly Income (All Time)", f"€{avg_monthly_all:,.2f}")
    col2.metric("Total Income (Selected Period)", f"€{total_period:,.2f}")
    
    # 2. Annual Growth Rate (CAGR or YoY)
    st.markdown("### 📈 Growth & Trends")
    
    # Annual totals
    annual_inc = full_income.groupby(full_income['date'].dt.year)['amount'].sum()
    
    # Determine which years to compare
    # Check if filtered_df has a specific year selected
    selected_years = filtered_df['date'].dt.year.unique()
    
    target_year = None
    if len(selected_years) == 1:
        target_year = selected_years[0]
    else:
        # Default to latest year in full dataset if multiple selected
        if not annual_inc.empty:
            target_year = annual_inc.index.max()

    if target_year and (target_year - 1) in annual_inc.index:
        current_val = annual_inc[target_year]
        prev_val = annual_inc[target_year - 1]
        
        growth_pct = ((current_val - prev_val) / prev_val) * 100
        col3.metric(f"Growth ({target_year - 1} vs {target_year})", f"{growth_pct:+.1f}%")
    else:
        if target_year:
            col3.info(f"No data for {target_year - 1} to compare.")
        else:
            col3.info("Select a single year to see growth.")
            
    # Chart: Annual Trend
    fig_annual = px.bar(x=annual_inc.index, y=annual_inc.values, title="Annual Income Trend", labels={'x': 'Year', 'y': 'Total Income'})
    st.plotly_chart(fig_annual, use_container_width=True)

    st.divider()

    # 3. Income Sources Decomposition
    st.markdown("### 🏦 Income Sources")
    if not filtered_income.empty:
        # Pie chart of categories
        inc_by_cat = filtered_income.groupby('category')['amount'].sum().reset_index()
        fig_pie = px.pie(inc_by_cat, values='amount', names='category', title="Income Mix (Selected Period)", hole=0.4)
        
        # Trend of sources over time
        # Stacked bar
        monthly_cat = filtered_income.groupby([pd.Grouper(key='date', freq='ME'), 'category'])['amount'].sum().reset_index()
        fig_stack = px.bar(monthly_cat, x='date', y='amount', color='category', title="Income Sources over Time")
        
        c1, c2 = st.columns(2)
        c1.plotly_chart(fig_pie, use_container_width=True)
        c2.plotly_chart(fig_stack, use_container_width=True)
