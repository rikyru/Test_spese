"""Vista Salute finanziaria."""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from src.utils import SUBSCRIPTION_TAGS, liquid_balance
from src.metrics import (
    real_income,
    real_expenses,
    _is_subscription,
    in_progress_period,
    AVG_BASIS_NOTE,
    avg_monthly,
    SALARY_CATEGORY,
    salary_coverage,
)


# ---------------------------------------------------------------------------
# SALUTE FINANZIARIA
# ---------------------------------------------------------------------------

def render_financial_health(full_df, data_manager):
    st.subheader("💚 Salute Finanziaria")

    df = full_df.copy()
    df['date'] = pd.to_datetime(df['date'])

    exp = real_expenses(df)
    inc = real_income(df)
    if exp.empty:
        st.info("Dati insufficienti.")
        return
    exp['abs_amount'] = exp['amount'].abs()
    exp['my'] = exp['date'].dt.to_period('M')
    inc['my'] = inc['date'].dt.to_period('M')

    # Mesi COMPLETI per medie/statistiche (il mese in corso parziale le falserebbe)
    _ip = in_progress_period(df)
    monthly_exp = exp.groupby('my')['abs_amount'].sum().sort_index()
    monthly_inc = inc.groupby('my')['amount'].sum().sort_index()
    if _ip is not None:
        monthly_exp = monthly_exp.drop(_ip, errors='ignore')
        monthly_inc = monthly_inc.drop(_ip, errors='ignore')
    net_worth = df['amount'].sum()          # patrimonio netto (include crediti/debiti virtuali)
    liquidity = liquid_balance(df)          # solo denaro spendibile
    avg_exp_12 = avg_monthly(df)

    # ===== A. FONDO EMERGENZA =====
    st.markdown("### 🛟 Fondo Emergenza")
    runway = liquidity / avg_exp_12 if avg_exp_12 > 0 else 0

    a1, a2, a3 = st.columns(3)
    a1.metric("Liquidità spendibile", f"€{liquidity:,.0f}",
              help=f"Esclusi i conti virtuali (Partner, Prestiti). Patrimonio netto totale: €{net_worth:,.0f}")
    a2.metric("Spesa Media/Mese (12m)", f"€{avg_exp_12:,.0f}", help=AVG_BASIS_NOTE)
    a3.metric("Autonomia (Runway)", f"{runway:.1f} mesi")

    gmax = max(12, runway * 1.2)
    fig_g = go.Figure(go.Indicator(
        mode="gauge+number", value=runway,
        number={'suffix': ' mesi', 'font': {'size': 34}},
        title={'text': "Mesi coperti senza entrate", 'font': {'size': 15}},
        gauge={'axis': {'range': [0, gmax]}, 'bar': {'color': '#2196F3'},
               'steps': [{'range': [0, 3], 'color': '#FFCDD2'},
                         {'range': [3, 6], 'color': '#FFF9C4'},
                         {'range': [6, gmax], 'color': '#C8E6C9'}],
               'threshold': {'line': {'color': '#4CAF50', 'width': 4},
                             'thickness': 0.8, 'value': 6}}))
    fig_g.update_layout(height=280)
    st.plotly_chart(fig_g, use_container_width=True)

    if runway < 3:
        st.error("⚠️ Sotto i 3 mesi: fondo emergenza da rinforzare.")
    elif runway < 6:
        st.warning("📊 Tra 3 e 6 mesi: discreto, l'ideale è 6+.")
    else:
        st.success("🎉 6+ mesi di autonomia: ottimo cuscinetto.")

    st.divider()

    # ===== B. PATRIMONIO + OBIETTIVO =====
    st.markdown("### 📈 Patrimonio Netto & Obiettivo")
    nw = df.sort_values('date').copy()
    nw['cum'] = nw['amount'].cumsum()
    nw_m = nw.groupby(nw['date'].dt.to_period('M'))['cum'].last().reset_index()
    nw_m.columns = ['periodo', 'cum']
    nw_m['mese'] = nw_m['periodo'].astype(str)
    fig_nw = px.area(nw_m, x='mese', y='cum', title="Patrimonio Netto nel Tempo",
                     labels={'cum': '€', 'mese': 'Mese'})
    fig_nw.update_traces(line_color='#009688', fillcolor='rgba(0,150,136,0.25)')
    fig_nw.update_layout(height=340, hovermode='x unified')
    st.plotly_chart(fig_nw, use_container_width=True)

    monthly_net = (monthly_inc - monthly_exp).dropna()
    avg_save = monthly_net.tail(12).mean() if not monthly_net.empty else 0

    g1, g2 = st.columns([1, 2])
    goal = g1.number_input("🎯 Obiettivo patrimonio €", min_value=0,
                           value=int(round(net_worth / 1000) * 1000) + 10000, step=1000)
    if goal <= net_worth:
        g2.info("🎉 Obiettivo già raggiunto!")
    elif avg_save > 0:
        months_to = (goal - net_worth) / avg_save
        eta = (pd.Timestamp.today() + pd.DateOffset(months=int(round(months_to)))).strftime('%b %Y')
        g2.success(f"Risparmiando ~€{avg_save:,.0f}/mese (media 12m), raggiungi "
                   f"**€{goal:,.0f}** tra ~**{months_to:.0f} mesi** (≈ {eta}).")
    else:
        g2.warning("Col risparmio medio attuale (≤ 0) l'obiettivo non è raggiungibile: "
                   "serve aumentare il risparmio mensile.")

    st.divider()

    # ===== C. MESI IN DEFICIT =====
    st.markdown("### 🔴 Mesi in Deficit")
    mdf = pd.DataFrame({'inc': monthly_inc, 'exp': monthly_exp}).fillna(0.0)
    mdf['net'] = mdf['inc'] - mdf['exp']
    mdf['mese'] = mdf.index.astype(str)
    n_def = int((mdf['net'] < 0).sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Mesi in Deficit", f"{n_def}/{len(mdf)}", f"{n_def / len(mdf) * 100:.0f}%",
              delta_color="inverse")
    worst = mdf.loc[mdf['net'].idxmin()]
    c2.metric("Mese Peggiore", worst['mese'], f"€{worst['net']:,.0f}", delta_color="inverse")
    streak = 0
    for v in reversed(mdf['net'].tolist()):
        if v >= 0:
            streak += 1
        else:
            break
    c3.metric("Streak Positivo (recente)", f"{streak} mesi")

    colors = ['#EF5350' if v < 0 else '#66BB6A' for v in mdf['net']]
    fig_d = go.Figure(go.Bar(x=mdf['mese'], y=mdf['net'], marker_color=colors))
    fig_d.update_layout(height=320, title="Netto Mensile (entrate − spese reali)",
                        yaxis_title='€', xaxis_title='Mese')
    st.plotly_chart(fig_d, use_container_width=True)

    st.divider()

    # ===== C2. SOLO STIPENDIO =====
    st.markdown("### 💼 Solo Stipendio")
    st.caption("Lo stipendio da solo copre le tue spese? Spese reali con le condivise alla "
               "**tua quota** stimata (regole di Spese Condivise); escluse le altre entrate "
               "(regali, rimborsi, 730…). Solo mesi completi.")
    sc = salary_coverage(df, data_manager.rules_engine.rules.get('split_config', {}))
    if sc.empty or sc['stipendio'].sum() <= 0:
        st.info(f"Nessuna entrata in categoria '{SALARY_CATEGORY}'.")
    else:
        last12 = sc.tail(12)
        bal12 = float(last12['saldo'].sum())
        covered = int((last12['saldo'] >= 0).sum())
        s1, s2, s3 = st.columns(3)
        s1.metric("Saldo ultimi 12 mesi", f"€{bal12:,.0f}", f"€{bal12 / len(last12):+,.0f}/mese",
                  delta_color="normal")
        s2.metric("Mesi coperti dallo stipendio", f"{covered}/{len(last12)}")
        if bal12 < 0:
            s3.metric("Taglio per stare in pari", f"€{-bal12 / len(last12):,.0f}/mese",
                      help="Riduzione media delle spese per coprirle col solo stipendio")
        else:
            s3.metric("Margine", f"€{bal12 / len(last12):,.0f}/mese",
                      help="Quanto avanza in media dello stipendio")

        hist = sc.tail(36).copy()
        hist['media12'] = sc['saldo'].rolling(12, min_periods=6).mean().tail(36)
        hist['mese'] = hist.index.astype(str)
        fig_s = go.Figure(go.Bar(x=hist['mese'], y=hist['saldo'], name='Saldo mese',
                                 marker_color=['#EF5350' if v < 0 else '#66BB6A' for v in hist['saldo']]))
        fig_s.add_trace(go.Scatter(x=hist['mese'], y=hist['media12'], name='Media mobile 12m',
                                   mode='lines', line=dict(color='#FFA726', width=3)))
        fig_s.update_layout(height=320, title="Stipendio − tue spese, mese per mese",
                            yaxis_title='€', xaxis_title='Mese', legend=dict(orientation='h', y=-0.25))
        st.plotly_chart(fig_s, use_container_width=True)

        yearly = sc.groupby(sc.index.year).agg(Mesi=('saldo', 'size'), Stipendio=('stipendio', 'sum'),
                                               Spese=('mie_spese', 'sum'), Saldo=('saldo', 'sum'),
                                               Coperti=('saldo', lambda v: int((v >= 0).sum())))
        yearly['Al mese'] = yearly['Saldo'] / yearly['Mesi']
        yearly['Coperti'] = yearly['Coperti'].astype(str) + '/' + yearly['Mesi'].astype(str)
        for c in ['Stipendio', 'Spese', 'Saldo', 'Al mese']:
            yearly[c] = yearly[c].apply(lambda x: f"€{x:,.0f}")
        yearly.index.name = 'Anno'
        st.dataframe(yearly[['Stipendio', 'Spese', 'Saldo', 'Al mese', 'Coperti']].sort_index(ascending=False),
                     use_container_width=True)

    st.divider()

    # ===== D. FISSE vs VARIABILI + ABBONAMENTI =====
    st.markdown("### 🔒 Spese Fisse vs Variabili")
    st.caption("Stima: 'fissa' = tag mutuo/condominio/affitto/abbonamento/ricorrente, "
               "categoria fissa (Fatture, Affitto, Alloggio), o mutuo/affitto/condominio nella descrizione.")

    FIXED_TAGS = {'abbonamento', 'subscription', 'recurring',
                  'mutuo', 'condominio', 'affitto'} | SUBSCRIPTION_TAGS
    FIXED_CATS = {'fatture', 'affitto', 'alloggio'}
    FIXED_DESC_KW = ('mutuo', 'affitto', 'condominio')

    def _is_fixed(row):
        t = row['tags']
        if hasattr(t, 'tolist'):
            t = t.tolist()
        if isinstance(t, list) and any(str(x).lower() in FIXED_TAGS for x in t):
            return True
        if str(row['category']).lower() in FIXED_CATS:
            return True
        desc = str(row['description']).lower()
        return any(kw in desc for kw in FIXED_DESC_KW)

    exp2 = exp.copy()
    exp2['tipo'] = exp2.apply(lambda r: 'Fissa' if _is_fixed(r) else 'Variabile', axis=1)
    if _ip is not None:
        exp2 = exp2[exp2['my'] != _ip]            # grafico e quote su mesi completi
    fv = exp2.groupby(['my', 'tipo'])['abs_amount'].sum().reset_index()
    fv['mese'] = fv['my'].astype(str)
    fig_fv = px.area(fv, x='mese', y='abs_amount', color='tipo',
                     title="Fisse vs Variabili nel Tempo",
                     color_discrete_map={'Fissa': '#EF553B', 'Variabile': '#636EFA'},
                     labels={'abs_amount': '€', 'mese': 'Mese', 'tipo': 'Tipo'})
    fig_fv.update_layout(height=340, hovermode='x unified')
    st.plotly_chart(fig_fv, use_container_width=True)

    fixed_tot = exp2[exp2['tipo'] == 'Fissa']['abs_amount'].sum()
    tot = exp2['abs_amount'].sum()
    inc_tot = monthly_inc.sum()
    d1, d2 = st.columns(2)
    d1.metric("Quota Spese Fisse", f"{(fixed_tot / tot * 100) if tot else 0:.0f}%",
              help="Sul totale delle spese")
    if inc_tot > 0:
        d2.metric("Fisse su Entrate", f"{fixed_tot / inc_tot * 100:.0f}%",
                  help="Quanto del reddito è impegnato in spese fisse")

    st.markdown("#### 📺 Abbonamenti nel Tempo")
    st.caption("Rilevati dai tag di servizio (spotify, nowtv, dazn, disney, prime, plex…), "
               "non dal tag generico 'abbonamento' che include i trasporti.")

    # Abbonamenti configurati nelle ricorrenti (fonte di verità dell'utente)
    try:
        rec = data_manager.get_recurring()
    except Exception:
        rec = pd.DataFrame()
    if not rec.empty:
        _svc = ['nowtv', 'now tv', 'disney', 'plex', 'netflix', 'spotify', 'dazn',
                'prime', 'sky', 'youtube', 'icloud', 'adobe', 'mubi', 'paramount', 'infinity']
        rn = rec['name'].astype(str).str.lower()
        sub_rec = rec[rn.apply(lambda n: any(s in n for s in _svc))]
        if not sub_rec.empty:
            st.caption("🔁 Configurati nelle ricorrenti: " +
                       " · ".join(f"{r['name']} €{abs(r['amount']):,.0f}/{str(r.get('frequency','Monthly'))[:3].lower()}"
                                  for _, r in sub_rec.iterrows()))

    subs = exp[exp['tags'].apply(_is_subscription)]
    if subs.empty:
        st.caption("Nessuna spesa con tag di servizio in abbonamento.")
    else:
        sm = subs.groupby('my')['abs_amount'].sum().sort_index()
        if _ip is not None:
            sm = sm.drop(_ip, errors='ignore')   # trend solo su mesi completi
        sm_df = sm.reset_index()
        sm_df['mese'] = sm_df['my'].astype(str)
        fig_s = px.bar(sm_df, x='mese', y='abs_amount', title="Costo Abbonamenti/Mese",
                       labels={'abs_amount': '€', 'mese': 'Mese'})
        if len(sm) >= 3:
            sm_df['ma3'] = sm_df['abs_amount'].rolling(3, min_periods=1).mean()
            fig_s.add_scatter(x=sm_df['mese'], y=sm_df['ma3'], name='Media mobile 3m',
                              line=dict(color='#EF553B', dash='dot'))
        fig_s.update_layout(height=320, hovermode='x unified')
        st.plotly_chart(fig_s, use_container_width=True)
        if len(sm) >= 6:
            creep = np.polyfit(np.arange(len(sm)), sm.values, 1)[0]
            if creep > 1:
                st.warning(f"📈 Gli abbonamenti crescono di ~€{creep:+.0f}/mese: attenzione al *subscription creep*.")
            elif creep < -1:
                st.success(f"📉 Abbonamenti in calo (~€{creep:+.0f}/mese).")
            else:
                st.info("➡️ Costo abbonamenti stabile.")
