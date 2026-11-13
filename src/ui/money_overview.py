"""Cima della Home: quanti soldi hai e dove (conti, risparmi, investimenti)."""
import datetime
import pandas as pd
import streamlit as st
from src.utils import VIRTUAL_ACCOUNTS, INVESTMENT_ACCOUNTS, liquid_balance, savings_accounts, accrued_interest
from src.metrics import avg_monthly, AVG_BASIS_NOTE

FREQ_PER_MONTH = {'Monthly': 1.0, 'Bimonthly': 0.5, 'Quarterly': 1 / 3, 'Yearly': 1 / 12, 'Weekly': 4.33}


def _card(title, value, sub=None, color=None, tag=None):
    color = color or ("#2E7D32" if value >= 0 else "#C62828")
    with st.container(border=True):
        st.markdown(f"**{title}**" + (f" &nbsp;<span style='background:#ECEFF1;color:#455A64;border-radius:4px;"
                                       f"padding:1px 6px;font-size:0.7em;font-weight:600;'>{tag}</span>" if tag else ""),
                    unsafe_allow_html=True)
        st.markdown(f"<h3 style='margin:0; color:{color};'>€ {value:,.2f}</h3>", unsafe_allow_html=True)
        if sub:
            st.caption(sub)


def _investment_values(data_manager, now_df):
    """Conto investimenti → (valore, versato, a prezzi di oggi?)."""
    from src.investments import live_portfolio
    out = {}
    for a in sorted(INVESTMENT_ACCOUNTS):
        rows = now_df[now_df['account'] == a]
        if rows.empty:
            continue
        try:
            pf, _ = live_portfolio(data_manager, a)
        except Exception:
            pf = pd.DataFrame()
        if not pf.empty:
            out[a] = (float(pf['value_now'].sum()), float(pf['cost'].sum()), True)
        else:
            paid_in = float(rows[rows['type'].isin(['Incoming Transfer', 'Outgoing Transfer'])]['amount'].sum())
            out[a] = (float(rows['amount'].sum()), paid_in, False)
    return out


def render_money_overview(df, data_manager, rules_engine):
    rules = rules_engine.rules
    main = data_manager.get_main_wallet()
    archived = set(rules.get('archived_accounts') or [])
    today = pd.Timestamp(datetime.date.today())

    # Saldi a oggi (le bollette con data di scadenza futura non sono ancora uscite)
    now_df = df[df['date'] <= today]
    bal = now_df.groupby('account')['amount'].sum()
    future = df[df['date'] > today]
    liquid = liquid_balance(now_df)
    # Interessi maturati sui conti risparmio dall'ultimo movimento registrato (stima)
    accrued = {}
    for a, s in savings_accounts(rules).items():
        rows = now_df[now_df['account'] == a]
        if not rows.empty:
            days = (today - rows['date'].max()).days
            accrued[a] = (accrued_interest(float(rows['amount'].sum()), s['rate'], s['tax'], days),
                          rows['date'].max(), s)
    liquid += sum(v for v, _, _ in accrued.values())
    inv = _investment_values(data_manager, now_df)
    invested = sum(v for v, _, _ in inv.values())
    total = liquid + invested

    st.markdown(
        f"<div style='padding:16px 20px;border-radius:10px;background:#1B5E20;color:white;margin-bottom:12px;'>"
        f"<div style='font-size:1rem;opacity:.85'>I tuoi soldi oggi</div>"
        f"<div style='font-size:2.3rem;font-weight:700;line-height:1.2'>€ {total:,.2f}</div>"
        f"<div style='font-size:.95rem;opacity:.85'>disponibili € {liquid:,.2f}"
        + (f" · investiti € {invested:,.2f}" if inv else "") + "</div></div>",
        unsafe_allow_html=True)

    # Addebiti ricorrenti mensili per conto (es. mutuo su MPS)
    rec_month = {}
    try:
        for _, r in data_manager.get_recurring().iterrows():
            rec_month[r['account']] = rec_month.get(r['account'], 0.0) + \
                abs(r['amount']) * FREQ_PER_MONTH.get(r['frequency'], 1.0)
    except Exception:
        pass

    accounts = [a for a in bal.index if a not in VIRTUAL_ACCOUNTS | archived | INVESTMENT_ACCOUNTS]
    accounts = sorted(accounts, key=lambda a: (a != main, -bal[a]))
    cards = []
    for a in accounts:
        sub, tag = None, None
        if a == main:
            tag = "principale"
            pend = future[future['account'] == a]['amount'].sum()
            sub = "Spese di tutti i giorni" + (f" · in uscita €{-pend:,.0f} (bollette future)" if pend < 0 else "")
        elif a in accrued:
            acc_v, since, s = accrued[a]
            sub = (f"Tasso {s['rate']:.2f}% lordo · +€{acc_v:,.2f} interessi maturati dal "
                   f"{since.strftime('%d/%m')} (stima, netti {100 - s['tax']:.0f}%)")
        elif rec_month.get(a, 0) >= 50:
            n = bal[a] / rec_month[a]
            sub = f"Copre ~{max(n, 0):.1f} mesi di addebiti (€{rec_month[a]:,.0f}/mese)" + \
                  (" — da ricaricare" if n < 2 else "")
        value = float(bal[a]) + (accrued[a][0] if a in accrued else 0.0)
        cards.append(dict(title=a, value=value, sub=sub, tag=tag))
    for a, (value, paid_in, live) in inv.items():
        gain = value - paid_in
        pct = gain / paid_in * 100 if paid_in else 0.0
        cards.append(dict(title=a, value=value,
                          sub=f"{gain:+,.2f}€ ({pct:+.1f}%) su €{paid_in:,.0f} investiti"
                              + (" · prezzi di oggi" if live else ""),
                          color="#1565C0" if gain >= 0 else "#C62828"))
    cols = st.columns(min(len(cards), 4) or 1)
    for i, c in enumerate(cards):
        with cols[i % len(cols)]:
            _card(**c)

    # Crediti: prestiti non ancora restituiti (fuori dalla liquidità)
    loans = float(bal.get('Prestiti', 0.0))
    if 'source_file' in now_df.columns:
        loans += float(now_df.loc[(now_df['account'] == 'Partner') & now_df['source_file'].isin(['loan', 'loan_repay']),
                                  'amount'].sum())
    if abs(loans) > 0.005:
        st.caption(f"Prestiti da ricevere: €{loans:,.2f} (non conteggiati nei soldi disponibili)")

    # Fondo emergenza: una riga, dettagli a richiesta
    avg_exp = avg_monthly(now_df)
    if avg_exp > 0:
        target = int(rules.get('emergency_target_months', 6) or 6)
        runway = liquid / avg_exp
        with st.expander(f"Fondo emergenza: i soldi disponibili coprono {runway:.1f} mesi di spese "
                         f"(obiettivo {target})"):
            typ_save = avg_monthly(now_df, 'income') - avg_exp
            st.caption(f"Spesa media €{avg_exp:,.0f}/mese. {AVG_BASIS_NOTE}.")
            new_tm = st.slider("Mesi obiettivo", 1, 12, target, key="ef_target")
            if new_tm != target:
                rules['emergency_target_months'] = int(new_tm)
                rules_engine.save_rules(rules)
                st.rerun()
            target_amt = target * avg_exp
            st.progress(min(liquid / target_amt, 1.0), text=f"€{liquid:,.0f} su €{target_amt:,.0f}")
            if liquid < target_amt:
                manca = target_amt - liquid
                st.caption(f"Mancano €{manca:,.0f}" + (f": risparmiando ~€{typ_save:,.0f}/mese ci arrivi in "
                                                       f"~{manca / typ_save:.0f} mesi." if typ_save > 0 else "."))
            else:
                st.caption("Obiettivo raggiunto.")
