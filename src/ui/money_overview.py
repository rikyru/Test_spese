"""Cima della Dashboard: quanti soldi hai e dove (conti, risparmi, investimenti)."""
import datetime
import pandas as pd
import streamlit as st
from src.utils import VIRTUAL_ACCOUNTS, INVESTMENT_ACCOUNTS, liquid_balance
from src.metrics import avg_monthly, AVG_BASIS_NOTE

FREQ_PER_MONTH = {'Monthly': 1.0, 'Bimonthly': 0.5, 'Quarterly': 1 / 3, 'Yearly': 1 / 12, 'Weekly': 4.33}


def _icon(name, wallet_rules):
    if name in wallet_rules and 'icon' in wallet_rules[name]:
        return wallet_rules[name]['icon']
    n = name.lower()
    if any(x in n for x in ['invest', 'trade', 'crypto', 'bitcoin']):
        return "📈"
    if any(x in n for x in ['risparmi', 'fondo', 'deposito', 'salvadanaio']):
        return "🐷"
    if any(x in n for x in ['contanti', 'cash', 'tasca']):
        return "💵"
    if any(x in n for x in ['banca', 'bank', 'unicredit', 'intesa', 'bnl', 'mps', 'posta', 'conto']):
        return "🏦"
    return "👛"


def _card(title, value, sub=None, color=None, badge=None):
    color = color or ("#2E7D32" if value >= 0 else "#C62828")
    with st.container(border=True):
        st.markdown(f"**{title}**" + (f" &nbsp;<span style='background:#FFF3E0;color:#E65100;border-radius:4px;"
                                       f"padding:1px 6px;font-size:0.7em;font-weight:700;'>{badge}</span>" if badge else ""),
                    unsafe_allow_html=True)
        st.markdown(f"<h3 style='margin:0; color:{color};'>€ {value:,.2f}</h3>", unsafe_allow_html=True)
        if sub:
            st.caption(sub)


def render_money_overview(df, data_manager, rules_engine):
    rules = rules_engine.rules
    wallet_rules = rules.get('wallets', {})
    main = data_manager.get_main_wallet()
    archived = set(rules.get('archived_accounts') or [])
    today = pd.Timestamp(datetime.date.today())

    # Saldi a oggi (le bollette con data di scadenza futura non sono ancora uscite)
    now_df = df[df['date'] <= today]
    bal = now_df.groupby('account')['amount'].sum()
    future = df[df['date'] > today]
    liquid = liquid_balance(now_df)
    investments = {a: float(bal.get(a, 0.0)) for a in sorted(INVESTMENT_ACCOUNTS) if a in bal.index}
    total = liquid + sum(investments.values())

    st.markdown(
        f"<div style='padding:16px 20px;border-radius:10px;background:linear-gradient(90deg,#4CAF50 0%,#2E7D32 100%);"
        f"color:white;margin-bottom:12px;'>"
        f"<div style='font-size:1rem;opacity:.9'>💰 I tuoi soldi oggi</div>"
        f"<div style='font-size:2.3rem;font-weight:700;line-height:1.2'>€ {total:,.2f}</div>"
        f"<div style='font-size:.95rem;opacity:.9'>di cui disponibili subito € {liquid:,.2f}"
        + (f" · investiti € {sum(investments.values()):,.2f}" if investments else "") + "</div></div>",
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
        sub = None
        if a == main:
            pend = future[future['account'] == a]['amount'].sum()
            sub = "Per le spese di tutti i giorni" + (f" · in uscita €{-pend:,.0f} (bollette future)" if pend < 0 else "")
        elif rec_month.get(a, 0) >= 50:
            n = bal[a] / rec_month[a]
            sub = ("⚠️ " if n < 2 else "") + f"Copre ~{max(n, 0):.1f} mesi di addebiti (€{rec_month[a]:,.0f}/mese)"
        cards.append((f"{_icon(a, wallet_rules)} {a}", float(bal[a]), sub, "⭐ PRINCIPALE" if a == main else None))
    for a, value in investments.items():
        rows = now_df[now_df['account'] == a]
        paid_in = float(rows[rows['type'].isin(['Incoming Transfer', 'Outgoing Transfer'])]['amount'].sum())
        gain = value - paid_in
        pct = gain / paid_in * 100 if paid_in else 0.0
        cards.append((f"📈 {a}", value, f"{gain:+,.2f}€ ({pct:+.1f}%) su €{paid_in:,.0f} investiti",
                      "#1565C0" if gain >= 0 else "#C62828"))
    cols = st.columns(min(len(cards), 4) or 1)
    for i, c in enumerate(cards):
        with cols[i % len(cols)]:
            if len(c) == 4 and isinstance(c[3], str) and c[3].startswith('#'):
                _card(c[0], c[1], c[2], color=c[3])
            else:
                _card(c[0], c[1], c[2], badge=c[3])

    # Crediti: prestiti non ancora restituiti (fuori dalla liquidità)
    loans = float(bal.get('Prestiti', 0.0))
    if 'source_file' in now_df.columns:
        loans += float(now_df.loc[(now_df['account'] == 'Partner') & now_df['source_file'].isin(['loan', 'loan_repay']),
                                  'amount'].sum())
    if abs(loans) > 0.005:
        st.caption(f"💸 Prestiti da ricevere: €{loans:,.2f} (non conteggiati nei soldi disponibili)")

    # Fondo emergenza: una riga, dettagli a richiesta
    avg_exp = avg_monthly(now_df)
    if avg_exp > 0:
        target = int(rules.get('emergency_target_months', 6) or 6)
        runway = liquid / avg_exp
        with st.expander(f"🛟 Fondo emergenza: i soldi disponibili coprono **{runway:.1f} mesi** di spese "
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
                st.caption("🎉 Obiettivo raggiunto.")
