"""Pagina 'Chiusura conti': saldi reali una volta al mese → l'app si allinea."""
import datetime
import json
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from src.utils import VIRTUAL_ACCOUNTS
from src.account_closing import closing_config, plan_closing, apply_closing, UNTRACKED_CATEGORY


def _describe(op):
    if op['kind'] == 'transfer':
        return f"🔁 Trasferimento €{op['amount']:,.2f}: {op['from']} → {op['to']} (neutro per le analisi)"
    if op['kind'] == 'adjustment':
        return f"⚖️ Aggiustamento neutro €{op['amount']:+,.2f} su {op['account']} (differenza accumulata nel tempo)"
    if op['amount'] < 0:
        return f"🕳️ Spesa «{UNTRACKED_CATEGORY}» €{-op['amount']:,.2f} su {op['account']} (soldi usciti ma non segnati)"
    return f"➕ Entrata «{UNTRACKED_CATEGORY}» €{op['amount']:,.2f} su {op['account']} (es. interessi, rimborsi non segnati)"


def render_account_closing(dm):
    st.header("🧾 Chiusura conti")
    st.caption("Una volta al mese scrivi i saldi reali (dall'app della banca). L'app confronta, ti dice quanto "
               "non hai registrato e si allinea aggiungendo pochi movimenti con la data della chiusura: "
               "lo storico non viene modificato.")
    rules = dm.rules_engine.rules
    cfg = closing_config(rules)
    groups = cfg['groups']
    main = cfg['main'] or dm.get_main_wallet()
    closings = dm.get_closings()
    first = closings.empty

    last_details = {}
    if not closings.empty:
        try:
            last_details = json.loads(closings.sort_values('created_at').iloc[-1]['details'] or '{}')
        except Exception:
            last_details = {}
        last_d = pd.to_datetime(closings['closing_date']).max()
        st.info(f"Ultima chiusura: **{last_d.strftime('%d/%m/%Y')}**")

    c_date = st.date_input("Data dei saldi", datetime.date.today(), key='cl_date')
    df = dm.get_transactions()
    df['date'] = pd.to_datetime(df['date'])
    upto = df[df['date'].dt.date <= c_date]
    app_bal = upto.groupby('account')['amount'].sum().to_dict()

    real, details = {}, {}
    cols = st.columns(len(groups))
    for col, (acc, subs) in zip(cols, groups.items()):
        with col:
            with st.container(border=True):
                st.markdown(f"**{acc}**" + (" ⭐" if acc == main else ""))
                tot = 0.0
                for sub in subs:
                    v = st.number_input(sub, value=float(last_details.get(sub, 0.0)), step=10.0,
                                        format="%.2f", key=f"cl_{acc}_{sub}")
                    details[sub] = v
                    tot += v
                real[acc] = round(tot, 2)
                st.caption(f"Reale €{tot:,.2f} · app €{app_bal.get(acc, 0.0):,.2f}")

    tbl = pd.DataFrame([{'Conto': a, 'App': app_bal.get(a, 0.0), 'Reale': real[a],
                         'Differenza': real[a] - app_bal.get(a, 0.0)} for a in groups])
    gap = tbl['Differenza'].sum()
    st.dataframe(tbl.style.format({'App': '€{:,.2f}', 'Reale': '€{:,.2f}', 'Differenza': '€{:+,.2f}'}),
                 hide_index=True, use_container_width=True)
    m1, m2 = st.columns(2)
    m1.metric("Totale reale", f"€{tbl['Reale'].sum():,.2f}", f"app €{tbl['App'].sum():,.2f}", delta_color="off")
    m2.metric("Differenza totale", f"€{gap:+,.2f}",
              help="Negativa: soldi usciti e non registrati. Positiva: entrate non registrate (es. interessi).")

    first_adj = st.checkbox("Prima chiusura: registra la differenza totale come aggiustamento neutro "
                            "(non conta come spesa del mese)", value=first, key='cl_first')
    ops = plan_closing(app_bal, real, main, first=first_adj)
    if not ops:
        st.success("I saldi coincidono: niente da registrare.")
    else:
        st.markdown("**Verrà registrato:**")
        for op in ops:
            st.markdown("- " + _describe(op))
    if not any(real.values()):
        st.warning("Inserisci i saldi reali prima di registrare.")
    elif st.button("✅ Registra chiusura", type="primary", key='cl_save'):
        apply_closing(dm, ops, c_date)
        dm.save_closing(c_date, [(a, app_bal.get(a, 0.0), real[a]) for a in groups], details)
        st.success(f"Chiusura registrata ({len(ops)} movimenti).")
        st.rerun()

    _archive_section(dm, groups, main)
    _history(closings)


def _archive_section(dm, groups, main):
    """Conti vecchi fuori dai gruppi: si svuotano su un conto attivo e si archiviano."""
    rules = dm.rules_engine.rules
    archived = set(rules.get('archived_accounts') or [])
    bal = dm.get_account_balances()
    others = [a for a in bal if a not in groups and a not in VIRTUAL_ACCOUNTS and a not in archived]
    if not others:
        return
    with st.expander(f"🗄️ Conti fuori dalla chiusura ({len(others)})"):
        st.caption("Conti che non usi più: il saldo viene trasferito su un conto attivo (trasferimento datato "
                   "oggi, neutro per le analisi) e il conto sparisce da saldi ed elenchi. I movimenti storici restano.")
        for a in others:
            c1, c2, c3 = st.columns([2, 2, 1])
            c1.markdown(f"**{a}** · €{bal[a]:,.2f}")
            target = c2.selectbox("Sposta il saldo su", list(groups), key=f"arch_t_{a}",
                                  index=list(groups).index(main) if main in groups else 0)
            if c3.button("Archivia", key=f"arch_{a}"):
                if abs(bal[a]) >= 0.01:
                    src, dst, amt = (a, target, bal[a]) if bal[a] > 0 else (target, a, -bal[a])
                    dm.add_transfer(src, dst, amt, datetime.date.today(),
                                    description=f"Chiusura conto {a} → {target}", tag='chiusura', source='closing')
                rules['archived_accounts'] = sorted(archived | {a})
                dm.rules_engine.save_rules(rules)
                st.rerun()


def _history(closings):
    if closings.empty:
        return
    st.markdown("#### 📜 Storico chiusure")
    g = closings.groupby('closing_date').agg(app=('app_balance', 'sum'), reale=('real_balance', 'sum'),
                                             diff=('diff', 'sum')).reset_index()
    if len(g) >= 2:
        fig = go.Figure(go.Bar(x=pd.to_datetime(g['closing_date']), y=g['diff'],
                               marker_color=['#E53935' if v < 0 else '#43A047' for v in g['diff']]))
        fig.update_layout(height=260, yaxis_title='€', title="Non registrato a ogni chiusura (− spese sfuggite)")
        st.plotly_chart(fig, use_container_width=True)
    st.dataframe(g.rename(columns={'closing_date': 'Data', 'app': 'App', 'reale': 'Reale', 'diff': 'Differenza'})
                 .style.format({'App': '€{:,.2f}', 'Reale': '€{:,.2f}', 'Differenza': '€{:+,.2f}'}),
                 hide_index=True, use_container_width=True)
