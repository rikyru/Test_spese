"""Vista Previsioni: spesa attesa, categorie, scenario fine anno, calendario liquidità."""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from src.utils import liquid_balance
from src.metrics import (
    real_income,
    real_expenses,
    in_progress_period,
    last_complete_period,
    monthly_totals,
    avg_monthly,
    MONTH_ABBR,
    spending_forecast,
    typical_income,
    category_overview,
    thirteenth_estimate,
)


# ---------------------------------------------------------------------------
# FORECASTING
# ---------------------------------------------------------------------------

def render_forecasting(df, full_df=None, data_manager=None):
    st.subheader("📈 Previsioni")

    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    # Mesi COMPLETI (mese in corso escluso), mesi senza spese a zero
    series = monthly_totals(df, 'expense', ref_df=full_df if full_df is not None else df)
    ip = in_progress_period(full_df if full_df is not None else df)
    fc = spending_forecast(series)
    if fc is None:
        st.write("Servono almeno 3 mesi completi di dati per il forecast.")
        return

    next_p = series.index[-1] + 1
    partial_val = None
    if ip is not None:
        cur = real_expenses(df[df['date'].dt.to_period('M') == ip])
        partial_val = float(cur['amount'].abs().sum())

    st.caption(f"Stima = media degli ultimi {fc['n']} mesi completi. Le spese mensili oscillano molto "
               "(viaggi, regali, spese di casa): più che il numero conta l'**intervallo**.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Spesa attesa {MONTH_ABBR[next_p.month]} {next_p.year}", f"€{fc['expected']:,.0f}")
    c2.metric("Intervallo tipico", f"€{fc['low']:,.0f} – €{fc['high']:,.0f}",
              help="8 mesi su 10 degli ultimi 12 sono caduti in questo intervallo (10°–90° percentile)")
    if fc['mae'] is not None:
        c3.metric("Affidabilità", f"±€{fc['mae']:,.0f}",
                  help=f"Errore medio di questa stima sugli ultimi mesi (ognuno previsto solo con i dati "
                       f"precedenti): ±{fc['mae_pct']:.0f}%")
    if fc['trend_pct'] is not None:
        c4.metric("Trend 12 mesi", f"{fc['trend_pct']:+.0f}%",
                  help="Media ultimi 12 mesi vs i 12 precedenti", delta_color="inverse",
                  delta=("in crescita" if fc['trend_pct'] > 3 else "in calo" if fc['trend_pct'] < -3 else "stabile"))
    if partial_val is not None:
        st.caption(f"ℹ️ Mese in corso ({MONTH_ABBR[ip.month]}) escluso dai calcoli: finora €{partial_val:,.0f}.")

    # --- Chart: storico 24 mesi + intervallo e stima del prossimo mese ---
    hist = series.tail(24)
    x = [p.to_timestamp() for p in hist.index]
    nx = next_p.to_timestamp()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=x, y=hist.values, name='Storico', marker_color='#636EFA', opacity=0.7))
    fig.add_trace(go.Scatter(x=x, y=series.rolling(12, min_periods=6).mean().tail(24).values,
                             mode='lines', name='Media 12 mesi', line=dict(color='#EF553B', width=2)))
    fig.add_trace(go.Scatter(x=[nx, nx], y=[fc['low'], fc['high']], mode='lines', name='Intervallo tipico',
                             line=dict(color='rgba(0,204,150,0.6)', width=14)))
    fig.add_trace(go.Scatter(x=[nx], y=[fc['expected']], mode='markers', name='Stima',
                             marker=dict(color='#00CC96', size=14, symbol='star')))
    fig.update_layout(title="Spese mensili e previsione del prossimo mese", xaxis_title="Mese",
                      yaxis_title="€", hovermode="x unified", height=420,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True)

    # --- Per categoria: quanto spendi di solito e com'è andato questo mese ---
    st.markdown("### 📂 Categorie: quanto spendi di solito")
    ref = full_df if full_df is not None else df
    co = category_overview(df, ref_df=ref)
    if co.empty:
        st.info("Dati insufficienti per le categorie.")
    else:
        last_p = last_complete_period(ref)
        cur_lbl = f"{MONTH_ABBR[ip.month]} finora" if ip is not None else None
        st.caption(f"**Media/mese** = ultimi {int(co['n_mesi'].iloc[0])} mesi completi, mesi senza spese inclusi: "
                   "è la cifra da mettere a budget. **Frequenza** dice se la categoria è fissa (12/12) "
                   "o saltuaria (es. viaggi): per quelle saltuarie la media è un accantonamento, non una spesa "
                   "che arriva ogni mese.")

        def stato(r):
            if ip is not None and r['mese_in_corso'] > r['media'] * 1.1 and r['media'] > 0:
                return "🔴 questo mese già sopra la media"
            if r['scarto_ultimo'] > max(r['media'] * 0.25, 50):
                return f"🟠 {MONTH_ABBR[last_p.month]} sopra la media"
            if r['scarto_ultimo'] < -max(r['media'] * 0.25, 50):
                return f"🟢 {MONTH_ABBR[last_p.month]} sotto la media"
            return "⚪ nella norma"

        tbl = pd.DataFrame({
            'Categoria': co['categoria'],
            'Media/mese': co['media'].map(lambda v: f"€{v:,.0f}"),
            'Frequenza': co.apply(lambda r: f"{r['mesi_con_spesa']}/{r['n_mesi']} mesi", axis=1),
            f"{MONTH_ABBR[last_p.month].capitalize()} {last_p.year}": co['ultimo'].map(lambda v: f"€{v:,.0f}"),
        })
        if cur_lbl:
            tbl[cur_lbl.capitalize()] = co['mese_in_corso'].map(lambda v: f"€{v:,.0f}")
        tbl['Stato'] = co.apply(stato, axis=1)
        st.dataframe(tbl, use_container_width=True, hide_index=True)
        st.caption(f"Totale medie: €{co['media'].sum():,.0f}/mese (= spesa media mensile).")

    from src.ui.seasonality import render_seasonality
    render_seasonality(df)

    # --- Scenario Fine Anno ---
    if full_df is not None:
        render_year_scenario(full_df, data_manager)
        render_commitments_calendar(full_df, data_manager)


# ---------------------------------------------------------------------------
# SCENARIO FINE ANNO
# ---------------------------------------------------------------------------

def render_year_scenario(full_df, data_manager=None):
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

    remaining_months = 12 - today.month  # mesi interi rimanenti dopo questo mese

    ytd_inc_df = real_income(ytd)
    ytd_exp_df = real_expenses(ytd).copy()
    ytd_exp_df['abs'] = ytd_exp_df['amount'].abs()
    ytd_exp_df['period'] = ytd_exp_df['date'].dt.to_period('M')
    ytd_income = ytd_inc_df['amount'].sum()
    ytd_expenses_total = ytd_exp_df['abs'].sum()

    # Modello IBRIDO: gli impegni noti (ricorrenti/rate) si contano in modo ESATTO;
    # le spese VARIABILI con la media degli ultimi 12 mesi completi (stessa base di
    # Salute e Previsioni); le entrate con l'entrata tipica (mediana 12 mesi).
    is_rec = (ytd_exp_df['source_file'] == 'Recurring') if 'source_file' in ytd_exp_df.columns \
        else pd.Series(False, index=ytd_exp_df.index)
    all_exp = real_expenses(df)
    var_exp = all_exp[all_exp['source_file'] != 'Recurring'] if 'source_file' in all_exp.columns else all_exp

    def _typical(mask):
        return avg_monthly(var_exp[mask], ref_df=df)

    typ_need = _typical(var_exp['necessity'] == 'Need')
    typ_want = _typical(var_exp['necessity'] == 'Want')
    typ_other = _typical(~var_exp['necessity'].isin(['Need', 'Want']))
    typ_income = typical_income(df)

    # Mese in corso: conta solo quello che MANCA rispetto a un mese tipico (lo
    # stipendio arriva in un colpo solo: una frazione del mese lo conterebbe due volte)
    cur_p = pd.Period(today, freq='M')
    cur_exp = ytd_exp_df[(ytd_exp_df['period'] == cur_p) & (~is_rec)]
    cur_inc = float(ytd_inc_df[ytd_inc_df['date'].dt.to_period('M') == cur_p]['amount'].sum())
    t13 = thirteenth_estimate(data_manager) if data_manager is not None else 0.0
    exp_cur_income = typ_income + (t13 if today.month == 12 else 0.0)
    rem_cur_income = max(exp_cur_income - cur_inc, 0.0)
    future_t13 = t13 if today.month < 12 else 0.0

    def _rem(typ, mask):
        return max(typ - float(cur_exp[mask.reindex(cur_exp.index, fill_value=False)]['abs'].sum()), 0.0)

    rem_need = _rem(typ_need, ytd_exp_df['necessity'] == 'Need')
    rem_want = _rem(typ_want, ytd_exp_df['necessity'] == 'Want')
    rem_other = _rem(typ_other, ~ytd_exp_df['necessity'].isin(['Need', 'Want']))
    proj_months = remaining_months

    # Impegni noti (ricorrenti/rate) ancora da pagare entro dicembre — CONTATI ESATTI
    end_of_year = date_type(current_year, 12, 31)
    remaining_recurring = 0.0
    remaining_installments_amt = 0.0
    rec_by_month = {}
    if data_manager is not None:
        try:
            proj_rec = data_manager.get_projected_recurring(end_of_year)
            if not proj_rec.empty:
                proj_rec = proj_rec.copy()
                proj_rec['date'] = pd.to_datetime(proj_rec['date'])
                fut = proj_rec[(proj_rec['date'].dt.date > today) & (proj_rec['amount'] < 0)].copy()
                if not fut.empty:
                    fut['abs'] = fut['amount'].abs()
                    remaining_recurring = fut['abs'].sum()
                    rec_by_month = fut.groupby(fut['date'].dt.month)['abs'].sum().to_dict()
                    rec_cfg = data_manager.get_recurring()
                    if not rec_cfg.empty and 'remaining_installments' in rec_cfg.columns:
                        rate_names = set(rec_cfg[rec_cfg['remaining_installments'].notna()]['name'])
                        remaining_installments_amt = fut[fut['name'].isin(rate_names)]['abs'].sum()
        except Exception:
            pass

    proj_income = rem_cur_income + typ_income * proj_months + future_t13
    proj_needs = rem_need + typ_need * proj_months          # variabili
    proj_wants = rem_want + typ_want * proj_months          # variabili
    proj_other = rem_other + typ_other * proj_months        # variabili
    proj_variable = proj_needs + proj_wants + proj_other
    proj_committed = remaining_recurring          # esatto
    proj_expenses = proj_variable + proj_committed

    ytd_net = ytd_income - ytd_expenses_total
    fy_net_base = ytd_net + proj_income - proj_expenses

    st.caption(f"Modello ibrido: **impegni noti** (ricorrenti/rate) contati in modo esatto, "
               f"**spese variabili** = media degli ultimi 12 mesi completi, **entrate** = entrata tipica (mediana 12 mesi). "
               f"Proiezione: resto di {MONTH_ABBR[today.month]} (quanto manca a un mese tipico) + "
               f"{proj_months} mesi" + (f" + tredicesima €{future_t13:,.0f} dalle buste paga" if future_t13 else "") + ".")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Entrata Tipica/Mese", f"€{typ_income:,.0f}")
    m2.metric("Need Variabile/Mese", f"€{typ_need:,.0f}",
              help="Necessarie variabili (spesa, benzina...), escluse le ricorrenti")
    m3.metric("Want Variabile/Mese", f"€{typ_want:,.0f}", help="Voluttuarie: la leva su cui tagliare")
    m4.metric("Impegni Noti (resto anno)", f"€{proj_committed:,.0f}",
              help="Ricorrenti/rate ancora da pagare entro dicembre, contate esatte"
                   + (f" · rate a termine €{remaining_installments_amt:,.0f}" if remaining_installments_amt > 0 else ""))

    # --- Dove puoi tagliare: solo la parte VARIABILE (Wants) ---
    st.divider()
    st.markdown("### ✂️ Dove puoi tagliare (resto dell'anno)")
    st.caption(f"Impegni noti €{proj_committed:,.0f} non tagliabili. Sul variabile, i Desideri (Want) sono la leva.")
    t1, t2, t3 = st.columns(3)
    t1.metric("Necessità variabili proiettate", f"€{proj_needs:,.0f}")
    t2.metric("Desideri proiettati", f"€{proj_wants:,.0f}")
    t3.metric("Quota Desideri (sul variabile)", f"{(proj_wants / proj_variable * 100) if proj_variable else 0:.0f}%")
    cut = st.slider("Simula un taglio dei Desideri", 0, 100, 20, step=5, format="%d%%", key="wants_cut")
    saved = proj_wants * cut / 100.0
    st.success(f"Tagliando il **{cut}%** dei Wants risparmi **€{saved:,.0f}** in più entro fine anno "
               f"→ risparmio stimato **€{fy_net_base + saved:,.0f}** (baseline €{fy_net_base:,.0f}).")

    st.divider()

    # 📋 Spese in programma (PERSISTENTI): voci una-tantum note da contare a fine anno
    st.markdown("### 📋 Spese in programma")
    st.caption("Spese future che sai già di dover sostenere (es. condominio residuo €650, revisione caldaia, "
               "bollo auto...). Restano salvate e vengono contate nella proiezione di fine anno e nel calendario liquidità.")

    planned = data_manager.get_planned() if data_manager is not None else pd.DataFrame()

    with st.form("planned_add_form", clear_on_submit=True):
        pc1, pc2, pc3 = st.columns([3, 2, 2])
        pl_name = pc1.text_input("Descrizione", placeholder="es. Condominio residuo")
        pl_amount = pc2.number_input("Importo €", min_value=0.0, step=10.0)
        pl_date = pc3.date_input("Entro il", value=date_type(current_year, 12, 31),
                                 min_value=today, max_value=date_type(current_year, 12, 31))
        if st.form_submit_button("➕ Aggiungi in programma") and data_manager is not None:
            if pl_name and pl_amount > 0:
                data_manager.add_planned(pl_name, pl_amount, pl_date)
                st.rerun()

    total_planned = 0.0
    planned_by_month = {}
    if planned is not None and not planned.empty:
        planned = planned.copy()
        planned['due_date'] = pd.to_datetime(planned['due_date'])
        for _, p in planned.iterrows():
            pr1, pr2, pr3, pr4 = st.columns([4, 2, 2, 1])
            pr1.markdown(f"**{p['name']}**")
            pr2.markdown(f"€{abs(p['amount']):,.0f}")
            pr3.caption(p['due_date'].strftime('%d/%m/%Y'))
            if pr4.button("🗑️", key=f"del_pl_{p['id']}"):
                data_manager.delete_planned(p['id'])
                st.rerun()
        pmask = (planned['due_date'].dt.date > today) & (planned['due_date'].dt.year == current_year)
        planned_future = planned[pmask]
        total_planned = planned_future['amount'].abs().sum()
        planned_by_month = (planned_future.assign(m=planned_future['due_date'].dt.month)
                            .groupby('m')['amount'].apply(lambda s: s.abs().sum()).to_dict())
    else:
        st.caption("Nessuna spesa in programma: aggiungine una qui sopra.")

    fy_net_scenario = fy_net_base - total_planned

    st.divider()
    st.markdown("### 📊 Proiezione Fine Anno")
    st.caption(f"Proiezione resto anno: entrate ~€{proj_income:,.0f} · spese ~€{proj_expenses:,.0f} "
               f"(variabile €{proj_variable:,.0f} + impegni noti €{proj_committed:,.0f}).")
    col1, col2, col3 = st.columns(3)
    col1.metric("Risparmio Baseline", f"€{fy_net_base:,.0f}", help="Senza le spese in programma")
    col2.metric("Spese in Programma", f"€{total_planned:,.0f}",
                delta=(f"-€{total_planned:,.0f}" if total_planned else None), delta_color="inverse")
    col3.metric("Risparmio Fine Anno", f"€{fy_net_scenario:,.0f}",
                delta=(f"€{fy_net_scenario - fy_net_base:,.0f}" if total_planned else None),
                delta_color="normal")

    if fy_net_scenario < 0:
        st.error(f"⚠️ Con le spese in programma finiresti l'anno in rosso di €{abs(fy_net_scenario):,.0f}.")
    elif total_planned > 0 and fy_net_base > 0 and fy_net_scenario < fy_net_base * 0.5:
        st.warning("📉 Le spese in programma dimezzano quasi il risparmio previsto.")
    elif fy_net_scenario >= 0:
        st.success(f"✅ Risparmio netto stimato a fine anno: **€{fy_net_scenario:,.0f}**"
                   + (f" (dopo €{total_planned:,.0f} di spese in programma)." if total_planned else "."))
    else:
        st.error(f"⚠️ A questo ritmo finiresti l'anno con un deficit di €{abs(fy_net_scenario):,.0f}.")

    # Chart mensile proiezione
    st.divider()
    st.markdown("### 📈 Cashflow Mensile Proiettato")

    chart_rows = []
    month_names_it = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu',
                      7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}

    # Mesi passati (YTD); il mese in corso = reale finora + quanto manca a un mese tipico
    for m in range(1, today.month + 1):
        m_df = ytd[ytd['date'].dt.month == m]
        inc = real_income(m_df)['amount'].sum()
        exp = real_expenses(m_df)['amount'].abs().sum()
        tipo = 'Storico'
        if m == today.month:
            inc += rem_cur_income
            exp += rem_need + rem_want + rem_other + rec_by_month.get(m, 0) + planned_by_month.get(m, 0)
            tipo = 'In corso (stima)'
        chart_rows.append({'mese': month_names_it[m], 'num': m,
                           'entrate': inc, 'spese': exp, 'tipo': tipo})

    # Mesi futuri (proiezione) — extra = spese in programma di quel mese
    extra_by_month = planned_by_month

    for m in range(today.month + 1, 13):
        extra = extra_by_month.get(m, 0)
        chart_rows.append({'mese': month_names_it[m], 'num': m,
                           'entrate': typ_income + (future_t13 if m == 12 else 0.0),
                           'spese': typ_need + typ_want + typ_other + rec_by_month.get(m, 0) + extra,
                           'tipo': 'Proiezione' if extra == 0 else 'Proiezione + Extra'})

    chart_df = pd.DataFrame(chart_rows)
    chart_df['netto'] = chart_df['entrate'] - chart_df['spese']

    fig = go.Figure()
    colors = {'Storico': '#636EFA', 'In corso (stima)': '#90CAF9', 'Proiezione': '#00CC96',
              'Proiezione + Extra': '#FFA15A'}
    for tipo in chart_df['tipo'].unique():
        sub = chart_df[chart_df['tipo'] == tipo]
        fig.add_trace(go.Bar(x=sub['mese'], y=sub['netto'], name=tipo,
                             marker_color=colors.get(tipo, '#AAAAAA')))

    fig.add_trace(go.Scatter(x=chart_df['mese'], y=chart_df['netto'].cumsum(),
                             mode='lines+markers', name='Cumulativo',
                             line=dict(color='#7E57C2', width=2, dash='dot'),
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
# CALENDARIO IMPEGNI (cashflow forward: impegni noti + bollette stagionali)
# ---------------------------------------------------------------------------

def render_commitments_calendar(full_df, data_manager):
    from datetime import date as date_type
    st.divider()
    st.subheader("📆 Calendario liquidità (fino a dicembre)")

    df = full_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    today = date_type.today()
    cy = today.year
    net_worth = liquid_balance(df)   # parte dalla liquidità spendibile (esclusi conti virtuali)

    exp = real_expenses(df).copy()
    exp['abs'] = exp['amount'].abs()
    exp['period'] = exp['date'].dt.to_period('M')
    inc = real_income(df).copy()

    # Un solo numero onesto: la SPESA TIPICA mensile = mediana del totale speso nei
    # mesi completi (include già tutto: mutuo, condominio, bollette, spesa...).
    # Niente doppio conteggio.
    # Ultimi 12 mesi completi (stessa base delle altre medie), mesi a zero inclusi
    typ_spend = avg_monthly(df)          # spesa media 12 mesi (come Salute e Previsioni)
    typ_income = typical_income(df)      # entrata tipica (mediana 12 mesi)
    t13 = thirteenth_estimate(data_manager) if data_manager is not None else 0.0
    cur_p = pd.Period(today, freq='M')
    spent_now = float(exp[exp['period'] == cur_p]['abs'].sum())
    got_now = float(inc[pd.to_datetime(inc['date']).dt.to_period('M') == cur_p]['amount'].sum())

    if typ_spend == 0 and typ_income == 0:
        st.info("Dati insufficienti per il calendario.")
        return

    st.caption("Proiezione su un 'mese tipico': **spesa media** ed **entrata tipica** degli ultimi 12 mesi "
               "completi (la spesa include già tutto ciò che registri — mutuo, bollette, spesa...). "
               "Il mese in corso conta solo quanto manca a un mese tipico; a dicembre si aggiunge la "
               "tredicesima delle buste paga. Serve a vedere la traiettoria, non il singolo movimento.")

    # Spese in programma (una-tantum note) per mese — queste sono FUTURE, non nello
    # storico, quindi vanno aggiunte (nessun doppio conteggio).
    planned_by_month = {}
    try:
        pl = data_manager.get_planned() if data_manager is not None else pd.DataFrame()
        if pl is not None and not pl.empty:
            pl = pl.copy()
            pl['due_date'] = pd.to_datetime(pl['due_date'])
            plf = pl[(pl['due_date'].dt.date > today) & (pl['due_date'].dt.year == cy)]
            planned_by_month = (plf.assign(m=plf['due_date'].dt.month)
                                .groupby('m')['amount'].apply(lambda s: s.abs().sum()).to_dict())
    except Exception:
        pass

    month_names_it = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu',
                      7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}

    rows = []
    liq = net_worth
    for m in range(today.month, 13):
        programmate = float(planned_by_month.get(m, 0.0))
        entrate = typ_income + (t13 if m == 12 else 0.0)
        spese_tip = typ_spend
        label = month_names_it[m]
        if m == today.month:   # resto del mese: quanto manca rispetto al tipico
            entrate = max(entrate - got_now, 0.0)
            spese_tip = max(typ_spend - spent_now, 0.0)
            label += ' (resto)'
        spese_m = spese_tip + programmate
        net = entrate - spese_m
        liq += net
        rows.append({'Mese': label, 'Entrate': entrate, 'Spese tipiche': spese_tip,
                     'In programma': programmate, 'Spese': spese_m, 'Netto': net, 'Liquidità': liq})

    if not rows:
        st.info("Nessun mese rimanente nell'anno.")
        return

    cal = pd.DataFrame(rows)
    has_planned = cal['In programma'].sum() > 0
    fig = go.Figure()
    fig.add_trace(go.Bar(x=cal['Mese'], y=cal['Entrate'], name='Entrate tipiche',
                         marker_color='#00CC96', opacity=0.7))
    fig.add_trace(go.Bar(x=cal['Mese'], y=cal['Spese tipiche'], name='Spese tipiche',
                         marker_color='#EF553B', opacity=0.7))
    if has_planned:
        fig.add_trace(go.Bar(x=cal['Mese'], y=cal['In programma'], name='In programma',
                             marker_color='#FFA15A'))
    fig.add_trace(go.Scatter(x=cal['Mese'], y=cal['Liquidità'], name='Liquidità proiettata',
                             mode='lines+markers', line=dict(color='#7E57C2', width=2, dash='dot'), yaxis='y2'))
    fig.update_layout(barmode='group', height=400, yaxis=dict(title='€/mese'),
                      yaxis2=dict(title='Liquidità €', overlaying='y', side='right', showgrid=False),
                      hovermode='x unified', legend=dict(orientation='h', yanchor='bottom', y=1.02))
    st.plotly_chart(fig, use_container_width=True)

    cols_show = ['Mese', 'Entrate', 'Spese tipiche'] + (['In programma'] if has_planned else []) + ['Netto', 'Liquidità']
    disp = cal[cols_show].copy()
    for c in [c for c in cols_show if c != 'Mese']:
        disp[c] = disp[c].apply(lambda x: f"€{x:,.0f}")
    st.dataframe(disp, use_container_width=True, hide_index=True)

    net_typ = typ_income - typ_spend
    if net_typ >= 0:
        st.success(f"In un mese tipico metti da parte ~€{net_typ:,.0f}. A dicembre la liquidità arriverebbe a ~€{cal.iloc[-1]['Liquidità']:,.0f}.")
    else:
        st.warning(f"In un mese tipico spendi ~€{abs(net_typ):,.0f} più di quanto entra. "
                   f"A dicembre la liquidità scenderebbe a ~€{cal.iloc[-1]['Liquidità']:,.0f}.")

    # Rate/impegni a termine in arrivo (solo riferimento sul TIMING; già dentro la spesa tipica)
    if data_manager is not None:
        try:
            pr = data_manager.get_projected_recurring(date_type(cy, 12, 31))
            rec_cfg = data_manager.get_recurring()
            if not pr.empty and not rec_cfg.empty and 'remaining_installments' in rec_cfg.columns:
                pr['date'] = pd.to_datetime(pr['date'])
                rate_names = set(rec_cfg[rec_cfg['remaining_installments'].notna()]['name'])
                fut = pr[(pr['date'].dt.date > today) & (pr['amount'] < 0) & (pr['name'].isin(rate_names))]
                if not fut.empty:
                    st.markdown("**📌 Rate a termine in arrivo** (per riferimento sul quando):")
                    for _, r in fut.sort_values('date').iterrows():
                        st.caption(f"· {r['date'].strftime('%d/%m')} — {r['name']} €{abs(r['amount']):,.0f}")
        except Exception:
            pass
