"""Vista Smart Insights."""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from src.metrics import (
    real_income,
    real_expenses,
    _tags_list,
    _is_subscription,
    drop_in_progress,
    AVG_BASIS_NOTE,
    last_complete_period,
    avg_monthly,
    comparable_prev_month,
    MONTH_ABBR,
    category_overview,
)


# ---------------------------------------------------------------------------
# SMART INSIGHTS
# ---------------------------------------------------------------------------

def render_smart_insights(full_df, filtered_df, data_manager=None):
    st.subheader("🧠 Smart Insights")

    if filtered_df.empty:
        st.info("Nessun dato disponibile per gli insight.")
        return

    full_df = full_df.copy()
    filtered_df = filtered_df.copy()
    full_df['date'] = pd.to_datetime(full_df['date'])
    filtered_df['date'] = pd.to_datetime(filtered_df['date'])

    all_expenses = real_expenses(full_df)
    all_expenses['abs_amount'] = all_expenses['amount'].abs()
    all_expenses['month_year'] = all_expenses['date'].dt.to_period('M')
    all_income = real_income(full_df)

    expenses = real_expenses(filtered_df)
    expenses['abs_amount'] = expenses['amount'].abs()
    income = real_income(filtered_df)

    if expenses.empty:
        st.write("Nessuna spesa da analizzare.")
        return

    expenses['month_year'] = expenses['date'].dt.to_period('M')
    total_expenses = expenses['abs_amount'].sum()
    total_income = income['amount'].sum() if not income.empty else 0

    # ====== 1. MESE IN CORSO (indipendente dal filtro, come in Dashboard) ======
    today = pd.Timestamp.today().normalize()
    cur_p = pd.Period(today, freq='M')
    cur_rows = all_expenses[all_expenses['month_year'] == cur_p]
    st.markdown(f"### 📅 {MONTH_ABBR[cur_p.month].capitalize()} {cur_p.year}: com'è andata finora")
    if not cur_rows.empty:
        spent = float(cur_rows['abs_amount'].sum())
        prev_df, p_lbl = comparable_prev_month(full_df, cur_p.year, cur_p.month, today)
        prev_same = float(real_expenses(prev_df)['amount'].abs().sum())
        avg12 = avg_monthly(full_df)
        c1, c2, c3 = st.columns(3)
        c1.metric("Speso finora", f"€{spent:,.0f}", help=f"€{spent / today.day:,.0f} al giorno su {today.day} giorni")
        c2.metric(f"Stesso periodo mese prima", f"€{prev_same:,.0f}",
                  delta=(f"{spent - prev_same:+,.0f}€ questo mese" if prev_same else None), delta_color="inverse")
        c3.metric("Spesa media mensile", f"€{avg12:,.0f}", help=AVG_BASIS_NOTE)
        st.caption(f"Confronto equo: 1–{today.day} di questo mese vs 1–{today.day} del mese prima. "
                   "Il mese intero si confronta con la media 12 mesi (le grosse spese fisse come mutuo e "
                   "condominio spesso arrivano a fine mese).")
    else:
        st.info("Nessuna spesa registrata nel mese in corso.")

    st.divider()

    # ====== 2. CATEGORIE FUORI DAL SOLITO (stessa base di Previsioni) ======
    st.markdown("### 📈 Categorie fuori dal solito")
    co = category_overview(full_df)
    if co.empty:
        st.info("Servono più mesi completi di dati.")
    else:
        last_p = last_complete_period(full_df)
        thr = co['media'].mul(0.25).clip(lower=50)
        moved = co[co['scarto_ultimo'].abs() > thr].copy()
        st.caption(f"Ultimo mese completo (**{MONTH_ABBR[last_p.month]} {last_p.year}**) confrontato con la "
                   f"media mensile degli ultimi {int(co['n_mesi'].iloc[0])} mesi. Solo le categorie che si "
                   "scostano di oltre il 25% (e almeno €50).")
        if moved.empty:
            st.success("Tutte le categorie nella norma.")
        else:
            moved = moved.sort_values('scarto_ultimo', ascending=False)
            st.dataframe(pd.DataFrame({
                'Categoria': moved['categoria'],
                'Tendenza': moved['scarto_ultimo'].map(lambda v: "🔴 sopra" if v > 0 else "🟢 sotto"),
                f"{MONTH_ABBR[last_p.month].capitalize()}": moved['ultimo'].map(lambda v: f"€{v:,.0f}"),
                'Media/mese': moved['media'].map(lambda v: f"€{v:,.0f}"),
                'Differenza': moved['scarto_ultimo'].map(lambda v: f"{v:+,.0f}€"),
            }), use_container_width=True, hide_index=True)

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
            title={'text': 'Tasso di risparmio', 'font': {'size': 18}},
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

    # Trend del tasso di risparmio mese per mese (su tutti i dati)
    if not all_income.empty:
        inc_m = all_income.groupby(all_income['date'].dt.to_period('M'))['amount'].sum()
        exp_m = (all_expenses.groupby('month_year')['abs_amount'].sum()
                 if not all_expenses.empty else pd.Series(dtype=float))
        sr = pd.DataFrame({'inc': inc_m}).join(pd.DataFrame({'exp': exp_m}), how='outer').fillna(0.0)
        sr = sr[sr['inc'] > 0].sort_index()
        sr = drop_in_progress(sr, full_df)   # escludi il mese parziale in corso
        if len(sr) >= 2:
            sr['rate'] = (sr['inc'] - sr['exp']) / sr['inc'] * 100
            sr['ma3'] = sr['rate'].rolling(3, min_periods=1).mean()
            sr['month_str'] = sr.index.astype(str)
            median_rate = sr['rate'].median()

            st.markdown(f"**📈 Tasso di risparmio mese per mese**  ·  tipico (mediana): **{median_rate:.0f}%**")
            st.caption("Mese in corso escluso. La mediana è più robusta della media contro i mesi eccezionali "
                       "(tredicesima, bonus, regali).")
            bar_colors = ['#00CC96' if v >= 20 else ('#FFB74D' if v >= 10 else '#EF5350')
                          for v in sr['rate']]
            fig_sr = go.Figure()
            fig_sr.add_trace(go.Bar(x=sr['month_str'], y=sr['rate'], name='Mensile',
                                    marker_color=bar_colors, opacity=0.85))
            fig_sr.add_trace(go.Scatter(x=sr['month_str'], y=sr['ma3'], name='Media mobile 3m',
                                        mode='lines', line=dict(color='#2196F3', width=2, dash='dot')))
            fig_sr.add_hline(y=median_rate, line_dash='dot', line_color='#7E57C2',
                             annotation_text=f'Mediana {median_rate:.0f}%', annotation_position='top right')
            fig_sr.add_hline(y=20, line_dash='dash', line_color='#4CAF50',
                             annotation_text='Obiettivo 20%', annotation_position='top left')
            fig_sr.update_layout(height=340, yaxis_title='% risparmio', xaxis_title='Mese',
                                 hovermode='x unified',
                                 legend=dict(orientation='h', yanchor='bottom', y=1.02))
            st.plotly_chart(fig_sr, use_container_width=True)

            recent = sr['rate'].tail(6)
            if len(recent) >= 3:
                sr_slope = np.polyfit(np.arange(len(recent)), recent.values, 1)[0]
                if sr_slope > 0.5:
                    st.success(f"📈 Il tasso di risparmio è in **miglioramento** (~{sr_slope:+.1f} punti/mese negli ultimi mesi).")
                elif sr_slope < -0.5:
                    st.warning(f"📉 Il tasso di risparmio sta **calando** (~{sr_slope:+.1f} punti/mese negli ultimi mesi).")
                else:
                    st.info("➡️ Tasso di risparmio **stabile** negli ultimi mesi.")

    st.divider()

    # ====== 5. SUBSCRIPTION TRACKER ======
    st.markdown("### 🔄 Costo Abbonamenti")

    # Abbonamenti reali: tag di servizio (non il generico 'abbonamento', che
    # include gli abbonamenti dei trasporti) + tabella ricorrenti
    sub_mask = filtered_df['tags'].apply(_is_subscription)
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
                rec_df = rec_df[rec_df['tags'].apply(_is_subscription)]
                rec_monthly_total = rec_df.apply(to_monthly, axis=1).sum() if not rec_df.empty else 0.0
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
        st.info("Nessun abbonamento trovato nel periodo. Sono riconosciuti dai tag dei servizi "
                "(netflix, spotify, disney, nowtv, prime, icloud, drive, plex…).")

    if rec_monthly_total > 0:
        st.info(f"📋 **Abbonamenti tra le ricorrenti:** €{rec_monthly_total:,.2f}/mese ({len(rec_names)} voci: {', '.join(rec_names[:6])}{'...' if len(rec_names) > 6 else ''})")

    st.divider()

    # (Proiezione annuale rimossa: ora nella tab Forecasting → Scenario Fine Anno,
    #  più completa e interattiva.)

    # ====== 7. WEEKDAY HEATMAP ======
    st.markdown("### 📅 Quando Spendi di Più?")

    weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    weekday_it = {'Monday': 'Lunedì', 'Tuesday': 'Martedì', 'Wednesday': 'Mercoledì',
                  'Thursday': 'Giovedì', 'Friday': 'Venerdì', 'Saturday': 'Sabato', 'Sunday': 'Domenica'}

    expenses['weekday'] = expenses['date'].dt.day_name()
    # Spesa media per GIORNO: totale di quel giorno della settimana / quante volte
    # quel giorno è capitato nel periodo (non la media per transazione)
    all_days = pd.date_range(expenses['date'].min().normalize(), expenses['date'].max().normalize(), freq='D')
    n_days = pd.Series(all_days.day_name()).value_counts()
    weekday_spend = expenses.groupby('weekday')['abs_amount'].agg(['sum', 'count']).reindex(weekday_order)
    weekday_spend['mean'] = weekday_spend['sum'] / n_days.reindex(weekday_order)
    weekday_spend.index = [weekday_it.get(d, d) for d in weekday_spend.index]
    weekday_spend = weekday_spend.dropna()

    if not weekday_spend.empty:
        top_day = weekday_spend['mean'].idxmax()
        top_day_avg = weekday_spend.loc[top_day, 'mean']

        fig_heatmap = px.bar(weekday_spend.reset_index(),
                             x='index', y='mean',
                             color='mean',
                             color_continuous_scale=['#C8E6C9', '#FFF9C4', '#FFCDD2'],
                             labels={'index': 'Giorno', 'mean': 'Spesa media (€)'},
                             title='Spesa media per giorno della settimana')
        fig_heatmap.update_layout(coloraxis_showscale=False, height=350)
        st.plotly_chart(fig_heatmap, use_container_width=True)
        st.info(f"💡 Il giorno in cui spendi di più è il **{top_day}**: in media €{top_day_avg:,.0f} ogni {top_day.lower()}.")

    st.divider()

    # ====== 8. TOP MERCHANTS ======
    st.markdown("### 🏪 Dove spendi più spesso")

    def _label(r):
        d = str(r['description'] or '').strip()
        if d and d.lower() not in ('nan', 'none'):
            return d
        t = [x for x in _tags_list(r['tags']) if str(x) != 'Recurring']
        return f"#{t[0]}" if t else f"({r['category']})"
    expenses['description'] = expenses.apply(_label, axis=1)
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
            cat_mask = expenses['category'].notna() & expenses['category'].str.lower().isin(
                ['ristoranti', 'restaurants', 'cibo fuori', 'food', 'mangiare e bere'])
            ristoranti = expenses[cat_mask]
            if not ristoranti.empty:
                rist_pct = (ristoranti['abs_amount'].sum() / total_expenses) * 100
                if rist_pct > 8:
                    monthly_rist = ristoranti['abs_amount'].sum() / max(len(expenses['month_year'].unique()), 1)
                    potential_save = monthly_rist * 0.3
                    tips.append(f"🍕 **Mangiare fuori = {rist_pct:.0f}% delle spese.** Cucinando a casa 2 volte in più a settimana potresti risparmiare ~€{potential_save:,.0f}/mese.")
        except Exception:
            pass

    # Tip: Subscriptions
    if avg_monthly_sub is not None and avg_monthly_sub > 50:
        tips.append(f"📺 **Abbonamenti = €{avg_monthly_sub:,.0f}/mese.** Rivedi i servizi che usi meno — anche tagliarne uno da €10 sono €120/anno.")

    # Tip: Savings rate
    if savings_rate is not None and total_income > 0:
        if savings_rate < 10:
            tips.append("💸 **Tasso di risparmio sotto il 10%.** Prova la regola 50/30/20: 50% necessità, 30% desideri, 20% risparmio.")
        elif savings_rate < 20:
            n_months_inc = max(len(income['date'].dt.to_period('M').unique()), 1) if not income.empty else 1
            extra_monthly = ((20 - savings_rate) / 100) * (total_income / n_months_inc)
            tips.append(f"📊 **Tasso di risparmio al {savings_rate:.0f}%.** Per arrivare al 20% servono €{extra_monthly:,.0f} in più al mese.")

    # Tip: Want spending
    if 'necessity' in expenses.columns:
        wants = expenses[expenses['necessity'] == 'Want']
        if not wants.empty and total_expenses > 0:
            want_pct = (wants['abs_amount'].sum() / total_expenses) * 100
            if want_pct > 35:
                cut_20 = wants['abs_amount'].sum() * 0.20 / max(len(expenses['month_year'].unique()), 1)
                tips.append(f"🛍️ **I desideri sono il {want_pct:.0f}% delle spese.** Tagliandone il 20% risparmi ~€{cut_20:,.0f}/mese (vedi la busta desideri in Dashboard).")

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
