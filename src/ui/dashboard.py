import streamlit as st
import plotly.express as px
import pandas as pd
import plotly.graph_objects as go
import datetime
import calendar
from src.rules_engine import RulesEngine
from src.metrics import real_income, real_expenses, comparable_prev_month
from src.ui.wants_envelope import render_wants_envelope
from src.ui.installments_panel import render_installments_panel
from src.ui.money_overview import render_money_overview

def render_dashboard(data_manager):
    st.header("Home")
    re = RulesEngine()
    
    try:
        df = data_manager.get_transactions()
        if df.empty:
            st.info("Nessun dato: importa un file dalla pagina Importa.")
            return

        # Ensure date is datetime
        df['date'] = pd.to_datetime(df['date'])
        df['year'] = df['date'].dt.year
        df['month'] = df['date'].dt.month

        # 1) Quanti soldi hai e dove
        render_money_overview(df, data_manager, re)
        try:
            _cl = data_manager.get_closings()
            _last = pd.to_datetime(_cl['closing_date']).max() if not _cl.empty else None
            if _last is None or (pd.Timestamp.today() - _last).days > 35:
                st.caption("" + (f"Ultima chiusura conti il {_last.strftime('%d/%m')}" if _last is not None
                                   else "Nessuna chiusura conti ancora") +
                           ": inserisci i saldi reali in **Chiusura conti** per tenere l'app allineata alla banca.")
        except Exception:
            pass
        try:
            from src.ui.data_quality import quality_checks, issues_count
            _n_dq = issues_count(quality_checks(df, data_manager.get_recurring(),
                                                re.rules.get('archived_accounts') or []))
            if _n_dq:
                st.caption(f"{_n_dq} controlli sui dati da guardare (possono falsare saldi e analisi) "
                           "→ **Impostazioni › Qualità dei dati**")
        except Exception:
            pass

        # 2) Spese: questo mese (busta desideri, rate), poi il periodo scelto
        st.divider()
        st.subheader("Spese")
        render_wants_envelope(df, re)
        render_installments_panel(data_manager)

        # Filtri periodo — barra compatta in alto (spostati dalla sidebar)
        min_date = df['date'].min().date()
        max_date = df['date'].max().date()
        today = datetime.date.today()
        month_names = {1:"Gen",2:"Feb",3:"Mar",4:"Apr",5:"Mag",6:"Giu",
                       7:"Lug",8:"Ago",9:"Set",10:"Ott",11:"Nov",12:"Dic"}

        mode_map = {"Mese": "Month", "Anno": "Year", "Personalizzato": "Custom", "Tutto": "All Time"}
        f1, f2, f3, f4 = st.columns([1.2, 1.2, 1.2, 2.2])
        mode_label = f1.selectbox("Periodo", list(mode_map.keys()), index=0)
        filter_mode = mode_map[mode_label]

        filtered_df = df.copy()
        selected_year = None
        selected_month = None

        available_years = sorted(list(set(df['year'].unique()) | {today.year}), reverse=True)
        default_year_idx = available_years.index(today.year) if today.year in available_years else 0

        if filter_mode == "Year":
            selected_year = f2.selectbox("Anno", available_years, index=default_year_idx)
            filtered_df = df[df['year'] == selected_year]
        elif filter_mode == "Month":
            selected_year = f2.selectbox("Anno", available_years, index=default_year_idx)
            selected_month = f3.selectbox("Mese", list(range(1, 13)), index=today.month - 1,
                                          format_func=lambda m: month_names[m])
            filtered_df = df[(df['year'] == selected_year) & (df['month'] == selected_month)]
        elif filter_mode == "Custom":
            start_date = f2.date_input("Da", min_date)
            end_date = f3.date_input("A", max_date)
            if start_date <= end_date:
                filtered_df = df[(df['date'].dt.date >= start_date) & (df['date'].dt.date <= end_date)]
            else:
                st.error("La data iniziale deve precedere quella finale.")

        # Filtro conto
        all_accounts = sorted(df['account'].dropna().unique().tolist())
        account_filter = f4.multiselect("Conti", options=all_accounts, placeholder="Tutti i conti")
        if account_filter:
            filtered_df = filtered_df[filtered_df['account'].isin(account_filter)]

        # --- Riepilogo del periodo (unica riga di KPI; confronto solo in vista Mese) ---
        is_month = filter_mode == "Month" and selected_year and selected_month
        m_exp_df = real_expenses(filtered_df)
        m_inc_df = real_income(filtered_df)
        m_exp = m_exp_df['amount'].abs().sum()
        m_inc = m_inc_df['amount'].sum()
        m_net = m_inc - m_exp
        m_rate = (m_net / m_inc * 100) if m_inc > 0 else 0
        d_exp = d_inc = d_net = None
        if is_month:
            # Mese precedente confrontabile (stessi giorni se il mese è in corso)
            p_df, p_lbl = comparable_prev_month(df, selected_year, selected_month)
            if account_filter:
                p_df = p_df[p_df['account'].isin(account_filter)]
            p_exp = real_expenses(p_df)['amount'].abs().sum()
            p_inc = real_income(p_df)['amount'].sum()
            if p_exp > 0:
                d_exp = f"{m_exp - p_exp:+,.0f}€ {p_lbl}"
            if p_inc > 0:
                d_inc = f"{m_inc - p_inc:+,.0f}€ {p_lbl}"
            if p_exp > 0 or p_inc > 0:
                d_net = f"{m_net - (p_inc - p_exp):+,.0f}€ {p_lbl}"
            period_lbl = f"{month_names[selected_month]} {selected_year}"
        elif filter_mode == "Year":
            period_lbl = str(selected_year)
        elif filter_mode == "Custom":
            period_lbl = f"{start_date.strftime('%d/%m/%Y')} – {end_date.strftime('%d/%m/%Y')}"
        else:
            period_lbl = "tutto lo storico"

        st.subheader(f"Riepilogo {period_lbl}")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Speso", f"€{m_exp:,.0f}", delta=d_exp, delta_color="inverse")
        r2.metric("Entrate", f"€{m_inc:,.0f}", delta=d_inc)
        r3.metric("Risparmio", f"€{m_net:,.0f}", delta=d_net)
        r4.metric("Tasso di risparmio", f"{m_rate:.0f}%")
        st.caption("Entrate e spese reali: trasferimenti tra conti, saldo iniziale e aggiustamenti esclusi.")

        if is_month:
            # Impegni fissi ancora da pagare entro fine mese (ricorrenti/rate)
            last_d = calendar.monthrange(selected_year, selected_month)[1]
            try:
                pend = data_manager.get_projected_recurring(datetime.date(selected_year, selected_month, last_d))
                pend = pend[(pd.to_datetime(pend['date']).dt.date > today) & (pend['amount'] < 0)] \
                    if not pend.empty else pend
                if not pend.empty:
                    st.caption(f"Ancora da pagare entro fine mese (ricorrenti/rate): "
                               f"**€{pend['amount'].abs().sum():,.0f}** — "
                               + ", ".join(f"{r['name']} €{abs(r['amount']):,.0f}" for _, r in pend.head(6).iterrows()))
            except Exception:
                pass

            # Riga narrativa: categoria top, spesa più grande, stato budget
            bits = []
            mm = m_exp_df.copy()
            if not mm.empty:
                mm['abs'] = mm['amount'].abs()
                byc = mm.groupby('category')['abs'].sum().sort_values(ascending=False)
                if not byc.empty:
                    bits.append(f"Categoria top: **{byc.index[0]}** (€{byc.iloc[0]:,.0f})")
                big = mm.sort_values('abs', ascending=False).iloc[0]
                bits.append(f"Spesa più grande: **€{abs(big['amount']):,.0f}** ({big['category']})")
                budgets = re.rules.get('budgets', {})
                if budgets:
                    over = sum(1 for c, b in budgets.items() if b and byc.get(c, 0) > b)
                    bits.append(f"**{over}** categorie oltre budget" if over else "Budget rispettati")
            if bits:
                st.caption("  ·  ".join(bits))

            # Calendario spese del mese (heatmap giornaliera)
            if not mm.empty:
                day_exp = mm.groupby(mm['date'].dt.day)['abs'].sum()
                weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(selected_year, selected_month)
                z, txt = [], []
                for wk in weeks:
                    zr, tr = [], []
                    for d in wk:
                        if d == 0:
                            zr.append(None); tr.append("")
                        else:
                            v = float(day_exp.get(d, 0) or 0)
                            zr.append(v)
                            tr.append(f"<b>{d}</b><br>€{v:,.0f}" if v > 0 else f"{d}")
                    z.append(zr); txt.append(tr)
                x_lbl = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom']
                y_lbl = [f"S{i+1}" for i in range(len(weeks))]
                fig_cal = go.Figure(go.Heatmap(
                    z=z, text=txt, texttemplate="%{text}", hoverinfo='text',
                    x=x_lbl, y=y_lbl, colorscale='Oranges', showscale=False, xgap=3, ygap=3))
                fig_cal.update_yaxes(autorange='reversed', showticklabels=False)
                fig_cal.update_layout(height=70 + len(weeks) * 60,
                                      margin=dict(l=6, r=6, t=6, b=6))
                with st.expander("Calendario spese del mese", expanded=False):
                    st.plotly_chart(fig_cal, use_container_width=True, key="cal_heat")
                    # Drill-down per giorno (selettore affidabile: il click sulla heatmap
                    # non è supportato in modo affidabile da Streamlit)
                    days_with = [int(d) for d in sorted(day_exp[day_exp > 0].index.tolist())]
                    if days_with:
                        day_opts = ["—"] + [f"{d} {month_names[selected_month]} · €{day_exp.get(d, 0):,.0f}"
                                            for d in days_with]
                        sel_day_lbl = st.selectbox("Vedi le spese di un giorno", day_opts, key="cal_day_sel")
                        if sel_day_lbl != "—":
                            dnum = int(sel_day_lbl.split()[0])
                            day_tx = filtered_df[filtered_df['date'].dt.day == dnum]
                            st.markdown(f"**Transazioni del {dnum} {month_names[selected_month]}** — "
                                        f"€{day_exp.get(dnum, 0):,.2f}")
                            st.dataframe(day_tx[['date', 'description', 'category', 'amount', 'tags']]
                                         .sort_values('date'), hide_index=True, use_container_width=True)

        # --- Grafici (entrate/spese REALI: niente trasferimenti tra conti) ---
        income_df = real_income(filtered_df)
        expense_df = real_expenses(filtered_df).copy()
        expense_df['abs_amount'] = expense_df['amount'].abs()

        col_charts_1, col_charts_2 = st.columns(2)

        with col_charts_1:
            st.subheader("Entrate per categoria")
            if not income_df.empty:
                income_by_cat = income_df.groupby('category')['amount'].sum().reset_index()
                fig_inc = px.pie(income_by_cat, values='amount', names='category', hole=0.4)
                inc_event = st.plotly_chart(fig_inc, use_container_width=True, on_select="rerun", key="pie_income")
                if inc_event and inc_event.selection and inc_event.selection.points:
                    sel_cat = inc_event.selection.points[0].get('label')
                    if sel_cat:
                        st.markdown(f"**Movimenti — {sel_cat}**")
                        drill = income_df[income_df['category'] == sel_cat][['date', 'description', 'amount', 'tags']] \
                            .sort_values('date', ascending=False)
                        st.dataframe(drill, use_container_width=True, hide_index=True)
            else:
                st.info("Nessuna entrata nel periodo.")

        with col_charts_2:
            st.subheader("Spese per categoria")
            if not expense_df.empty:
                exp_total = expense_df['abs_amount'].sum()
                exp_by_cat = expense_df.groupby('category')['abs_amount'].sum().reset_index() \
                    .sort_values('abs_amount', ascending=False)
                fig_exp = px.pie(exp_by_cat, values='abs_amount', names='category', hole=0.4)
                exp_event = st.plotly_chart(fig_exp, use_container_width=True, on_select="rerun", key="pie_expense")
                st.caption("Clicca una categoria (torta o tabella) per il dettaglio per tag.")

                cat_show = exp_by_cat.copy()
                cat_show['%'] = (cat_show['abs_amount'] / exp_total * 100).apply(lambda x: f"{x:.1f}%")
                cat_show['Importo'] = exp_by_cat['abs_amount'].apply(lambda x: f"€{x:,.2f}")
                cat_sel_event = st.dataframe(
                    cat_show[['category', 'Importo', '%']],
                    use_container_width=True, hide_index=True,
                    on_select="rerun", selection_mode="single-row", key="cat_table",
                    column_config={"category": "Categoria"}
                )

                sel_cat = None
                if exp_event and exp_event.selection and exp_event.selection.points:
                    sel_cat = exp_event.selection.points[0].get('label')
                elif cat_sel_event and cat_sel_event.selection and cat_sel_event.selection.rows:
                    sel_cat = exp_by_cat.iloc[cat_sel_event.selection.rows[0]]['category']

                if sel_cat:
                    cat_data = expense_df[expense_df['category'] == sel_cat]
                    cat_total = cat_data['abs_amount'].sum()
                    st.markdown(f"#### {sel_cat} — €{cat_total:,.2f} ({cat_total/exp_total*100:.0f}% del periodo)")

                    tag_expl = cat_data.explode('tags')
                    tag_expl['tags'] = tag_expl['tags'].astype(str)
                    tag_expl = tag_expl[~tag_expl['tags'].isin(['nan', 'None', '', 'Recurring'])]
                    if not tag_expl.empty:
                        tag_break = tag_expl.groupby('tags')['abs_amount'].sum().reset_index() \
                            .sort_values('abs_amount', ascending=False)
                        tag_break['%'] = tag_break['abs_amount'] / cat_total * 100
                        th = tag_break.head(12).copy()
                        th['lbl'] = th['%'].apply(lambda x: f"{x:.0f}%")
                        fig_tb = px.bar(th, x='tags', y='abs_amount', text='lbl', title=f"Per tag — {sel_cat}")
                        fig_tb.update_layout(height=280, showlegend=False, xaxis_title='', yaxis_title='€')
                        st.plotly_chart(fig_tb, use_container_width=True)

                        tb_show = tag_break.copy()
                        tb_show['Importo'] = tb_show['abs_amount'].apply(lambda x: f"€{x:,.2f}")
                        tb_show['%'] = tb_show['%'].apply(lambda x: f"{x:.1f}%")
                        st.dataframe(tb_show[['tags', 'Importo', '%']], use_container_width=True,
                                     hide_index=True, column_config={"tags": "Tag"})

                        def _has_tags(t):
                            if hasattr(t, 'tolist'):
                                t = t.tolist()
                            return isinstance(t, list) and any(x and str(x) not in ('nan', 'None', 'Recurring') for x in t)
                        untag = cat_data[~cat_data['tags'].apply(_has_tags)]['abs_amount'].sum()
                        if untag > 0:
                            st.caption(f"Senza tag: €{untag:,.2f} ({untag/cat_total*100:.0f}%)")
                    else:
                        st.caption("Nessun tag in questa categoria.")

                    st.markdown("**Movimenti**")
                    drill = cat_data[['date', 'description', 'amount', 'tags']].sort_values('date', ascending=False)
                    st.dataframe(drill, use_container_width=True, hide_index=True)
            else:
                st.info("Nessuna spesa nel periodo.")

        # --- Andamento: entrate, spese e netto (giornaliero nel mese, mensile altrimenti) ---
        def _flows(src, key):
            inc = real_income(src).groupby(key)['amount'].sum()
            exp = real_expenses(src).groupby(key)['amount'].sum().abs()
            out = pd.DataFrame({'Entrate': inc, 'Spese': exp}).fillna(0.0).sort_index()
            out['Netto'] = out['Entrate'] - out['Spese']
            return out

        def _flow_chart(fl, title, cumulative=False):
            fig = go.Figure()
            fig.add_trace(go.Bar(x=fl.index, y=fl['Entrate'], name='Entrate', marker_color='#4CAF50', opacity=0.7))
            fig.add_trace(go.Bar(x=fl.index, y=-fl['Spese'], name='Spese', marker_color='#EF5350', opacity=0.7))
            line = fl['Netto'].cumsum() if cumulative else fl['Netto']
            fig.add_trace(go.Scatter(x=fl.index, y=line, name='Netto cumulato' if cumulative else 'Netto',
                                     mode='lines+markers', line=dict(color='#2196F3', width=3)))
            fig.update_layout(title=title, barmode='relative', yaxis_title='€', hovermode='x unified',
                              legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1))
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("Andamento")
        if is_month:
            fl = _flows(filtered_df, filtered_df['date'].dt.date)
            if not fl.empty:
                _flow_chart(fl, f"Giorno per giorno — {period_lbl}", cumulative=True)
            year_df = df[df['year'] == selected_year]
            if account_filter:
                year_df = year_df[year_df['account'].isin(account_filter)]
            fl_y = _flows(year_df, year_df['date'].dt.to_period('M').dt.to_timestamp())
            if not fl_y.empty:
                _flow_chart(fl_y, f"Mese per mese — {selected_year}")
        else:
            fl = _flows(filtered_df, filtered_df['date'].dt.to_period('M').dt.to_timestamp())
            if not fl.empty:
                _flow_chart(fl, f"Mese per mese — {period_lbl}")

            st.subheader("Patrimonio netto nel tempo")
            nw_df = df.sort_values('date').copy()
            nw_df['cumulative_balance'] = nw_df['amount'].cumsum()
            if filter_mode == "Year":
                chart_nw = nw_df[nw_df['date'].dt.year == selected_year]
            elif filter_mode == "Custom":
                chart_nw = nw_df[(nw_df['date'].dt.date >= start_date) & (nw_df['date'].dt.date <= end_date)]
            else:
                chart_nw = nw_df
            if not chart_nw.empty:
                daily_nw = chart_nw.groupby('date')['cumulative_balance'].last().reset_index()
                fig_nw = px.area(daily_nw, x='date', y='cumulative_balance',
                                 labels={'cumulative_balance': 'Patrimonio (€)', 'date': 'Data'})
                fig_nw.update_layout(hovermode="x unified")
                fig_nw.update_traces(line_color='#009688', fillcolor='rgba(0, 150, 136, 0.3)')
                st.plotly_chart(fig_nw, use_container_width=True)
                st.caption("Somma di tutti i conti, compresi i crediti/debiti virtuali (Partner, Prestiti).")

        st.divider()

        # --- Budget mensili: hanno senso solo su un mese ---
        budgets = re.rules.get('budgets', {})
        if budgets:
            if is_month:
                st.subheader("Budget del mese")
                budget_cols = st.columns(min(len(budgets), 3))
                for idx, (cat, budget_amt) in enumerate(budgets.items()):
                    spent = expense_df[expense_df['category'] == cat]['abs_amount'].sum() if not expense_df.empty else 0.0
                    pct = min(spent / budget_amt, 1.0) if budget_amt > 0 else 0.0
                    status = " · oltre budget" if spent > budget_amt else (" · quasi al limite" if pct >= 0.9 else "")
                    with budget_cols[idx % min(len(budgets), 3)]:
                        with st.container(border=True):
                            st.markdown(f"**{cat}**{status}")
                            st.markdown(f"€{spent:,.2f} / €{budget_amt:,.2f}")
                            st.progress(pct, text=f"{pct*100:.0f}%")
            else:
                st.caption("I budget sono mensili: per vederli scegli il periodo «Mese».")
            st.divider()

        st.subheader("Spese più grandi del periodo")
        if not expense_df.empty:
            top_expenses = expense_df.sort_values('abs_amount', ascending=False).head(10)
            st.dataframe(top_expenses[['date', 'description', 'category', 'tags', 'amount']]
                         .style.format({'amount': '€{:.2f}'}),
                         use_container_width=True, hide_index=True,
                         column_config={'date': 'Data', 'description': 'Descrizione', 'category': 'Categoria',
                                        'tags': 'Tag', 'amount': 'Importo'})
        else:
            st.info("Nessuna spesa nel periodo.")

        with st.expander("Tutti i movimenti del periodo"):
            st.dataframe(filtered_df.sort_values('date', ascending=False), use_container_width=True)

    except Exception as e:
        st.error(f"Errore nel caricamento della dashboard: {e}")
        import traceback
        st.text(traceback.format_exc())
