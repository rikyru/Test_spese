"""Pagina Investimenti: portafoglio a prezzi di oggi, aggiornamento da screenshot
Revolut, andamento, dove sono i soldi e un simulatore per capire come investire."""
import datetime
import io
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from src.utils import INVESTMENT_ACCOUNTS, INVESTMENT_CATEGORY, VIRTUAL_ACCOUNTS
from src.metrics import avg_monthly
from src.investments import (parse_revolut_screenshot, reconcile_with_total, guess_yahoo, implied_cost,
                             live_portfolio, pac_projection)

ACCOUNT = sorted(INVESTMENT_ACCOUNTS)[0]
SINGLE_STOCK_LIMIT = 30   # % del portafoglio oltre cui un singolo titolo è "concentrazione"


@st.cache_resource(show_spinner=False)
def _ocr_reader():
    from src.ocr_engine import OCREngine
    return OCREngine()._get_reader()


def _is_etf(name):
    return any(k in str(name).upper() for k in ('ETF', 'UCITS', 'ISHARES', 'VANGUARD', 'XTRACKERS', 'AMUNDI'))


def render_investments(dm):
    st.header("Investimenti")
    pf, snap_date = live_portfolio(dm, ACCOUNT)
    if pf.empty:
        st.info("Nessun portafoglio ancora: carica lo screenshot del conto di intermediazione Revolut qui sotto.")
    else:
        _portfolio(pf, snap_date)
    _update_from_screenshot(dm)
    if not pf.empty:
        _history(dm, pf)
    _where_is_money(dm, pf)
    _learn(dm, pf)


# --------------------------------------------------------------------------
def _portfolio(pf, snap_date):
    st.subheader("Portafoglio oggi")
    value, cost = pf['value_now'].sum(), pf['cost'].sum()
    gain = value - cost
    c1, c2, c3 = st.columns(3)
    c1.metric("Valore oggi", f"€{value:,.2f}")
    c2.metric("Versato", f"€{cost:,.2f}")
    c3.metric("Risultato", f"€{gain:+,.2f}", f"{gain / cost * 100:+.1f}%" if cost else None)
    st.caption(f"Quantità dalla fotografia del {snap_date.strftime('%d/%m/%Y')}; prezzi di mercato aggiornati "
               "(Yahoo Finance, possono avere qualche minuto di ritardo; aggiornati al massimo ogni 6 ore).")

    pos = pf[~pf['is_cash']].sort_values('value_now', ascending=False)
    tbl = pd.DataFrame({
        'Titolo': pos['name'], 'Ticker': pos['yahoo'], 'Quantità': pos['qty'].round(4),
        'Valore': pos['value_now'].map(lambda v: f"€{v:,.2f}"),
        'Versato': pos['cost'].map(lambda v: f"€{v:,.2f}"),
        'Risultato': pos['gain'].map(lambda v: f"{v:+,.2f}€"),
        '%': pos['gain_pct'].map(lambda v: f"{v:+.1f}%"),
        'Peso': pos['weight'].map(lambda v: f"{v:.0f}%"),
        'Tipo': pos['name'].map(lambda n: 'ETF (diversificato)' if _is_etf(n) else 'Singola azione'),
    })
    st.dataframe(tbl, hide_index=True, use_container_width=True)
    cash = pf[pf['is_cash']]['value_now'].sum()
    if cash:
        st.caption(f"Liquidità non investita nel conto: €{cash:,.2f}")

    notes = []
    for _, r in pos.iterrows():
        if not _is_etf(r['name']) and r['weight'] > SINGLE_STOCK_LIMIT:
            notes.append(f"{r['name']} pesa il {r['weight']:.0f}% del portafoglio: se va male un'azienda sola, "
                         "ne risente tutto.")
        if r['gain_pct'] < -25:
            notes.append(f"{r['name']} è a {r['gain_pct']:.0f}% e da sola fa {r['gain']:+,.0f}€ del risultato.")
    stocks = pos[~pos['name'].map(_is_etf)]['value_now'].sum()
    if pos['value_now'].sum():
        notes.append(f"Singole azioni: {stocks / pos['value_now'].sum() * 100:.0f}% del portafoglio; ETF: "
                     f"{100 - stocks / pos['value_now'].sum() * 100:.0f}%.")
    for n in notes:
        st.markdown(f"- {n}")
    fig = px.pie(pos, values='value_now', names='name', hole=0.45)
    fig.update_layout(height=300, margin=dict(t=10, b=10), showlegend=True)
    st.plotly_chart(fig, use_container_width=True)


# --------------------------------------------------------------------------
def _update_from_screenshot(dm):
    with st.expander("Aggiorna da screenshot Revolut", expanded=False):
        st.caption("Carica lo screenshot della schermata *Conto di intermediazione* (con l'elenco dei titoli). "
                   "L'app legge titoli, quantità, valori e rendimenti: controlla la tabella e salva. Il valore "
                   "del conto investimenti si aggiorna da solo (variazione di valore, neutra per le analisi).")
        up = st.file_uploader("Screenshot", type=['png', 'jpg', 'jpeg'], key='inv_shot', label_visibility="collapsed")
        if up is not None and st.session_state.get('inv_parsed_name') != up.name:
            from PIL import Image
            import numpy as np
            with st.spinner("Lettura dello screenshot (la prima volta carica il modello OCR, ~1 minuto)..."):
                img = Image.open(io.BytesIO(up.getvalue())).convert('RGB')
                items = _ocr_reader().readtext(np.asarray(img))
                parsed = reconcile_with_total(parse_revolut_screenshot(items, img))
            st.session_state['inv_parsed'] = parsed
            st.session_state['inv_parsed_name'] = up.name
        parsed = st.session_state.get('inv_parsed')
        if not parsed:
            return
        if not parsed['positions']:
            st.warning("Non ho trovato titoli nello screenshot: usa la schermata con l'elenco delle posizioni.")
            return
        rows = [{'Titolo': p['name'], 'Simbolo': p.get('symbol'), 'Ticker Yahoo': guess_yahoo(p.get('symbol'), p.get('currency')),
                 'Quantità': p.get('qty'), 'Valuta': p.get('currency', 'EUR'), 'Valore €': p['value'],
                 'Rendimento %': p.get('pct'), 'Corretto': '⚠️ ricalcolato' if p.get('fixed') else ''}
                for p in parsed['positions']]
        edited = st.data_editor(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                                num_rows="dynamic", key='inv_editor',
                                disabled=['Corretto'])
        cash = st.number_input("Liquidità nel conto (saldo disponibile) €", value=float(parsed.get('cash') or 0.0),
                               step=1.0, key='inv_cash')
        total = edited['Valore €'].fillna(0).sum() + cash
        st.caption(f"Totale letto: €{total:,.2f}" + (f" (Revolut: €{parsed['total']:,.2f}, "
                                                     f"{parsed['total_pct']:+.2f}%)" if parsed.get('total') else "")
                   + ". Rendimento % negativo = in perdita (riconosciuto dal colore rosso).")
        d = st.date_input("Data dello screenshot", datetime.date.today(), key='inv_date')
        if st.button("Salva fotografia del portafoglio", type="primary", key='inv_save'):
            positions = []
            for _, r in edited.dropna(subset=['Titolo']).iterrows():
                positions.append({'name': r['Titolo'], 'symbol': r['Simbolo'], 'yahoo': r['Ticker Yahoo'],
                                  'qty': float(r['Quantità'] or 0), 'currency': r['Valuta'],
                                  'value': float(r['Valore €'] or 0),
                                  'price': (float(r['Valore €']) / float(r['Quantità'])) if r['Quantità'] else None,
                                  'pct': r['Rendimento %'],
                                  'cost': implied_cost(float(r['Valore €'] or 0), r['Rendimento %'])})
            if cash:
                positions.append({'name': 'Liquidità', 'value': cash, 'cost': cash, 'is_cash': True, 'currency': 'EUR'})
            dm.save_investment_snapshot(d, ACCOUNT, positions)
            # Il conto investimenti nell'app segue il valore della fotografia (variazione neutra)
            bal = float(dm.con.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account = ? "
                                       "AND date <= ?", [ACCOUNT, d]).fetchone()[0])
            diff = round(total - bal, 2)
            if abs(diff) >= 0.01:
                dm.con.execute("""
                    INSERT INTO transactions (id, date, amount, currency, account, category, tags, description,
                                              type, source_file, original_description)
                    VALUES (uuid(), ?, ?, 'EUR', ?, ?, ['investimenti'], 'Aggiornamento valore portafoglio',
                            'Adjustment', 'investments', 'Aggiornamento valore portafoglio')
                """, [d, diff, ACCOUNT, INVESTMENT_CATEGORY])
            st.session_state.pop('inv_parsed', None)
            st.success(f"Fotografia salvata. Valore del conto investimenti: €{total:,.2f} "
                       f"(variazione {diff:+,.2f}€).")
            st.rerun()


# --------------------------------------------------------------------------
def _history(dm, pf):
    s = dm.get_investment_snapshots(ACCOUNT)
    g = s.groupby('snapshot_date').agg(valore=('value', 'sum'), versato=('cost', 'sum')).reset_index()
    g['snapshot_date'] = pd.to_datetime(g['snapshot_date'])
    today = pd.Timestamp(datetime.date.today())
    if g['snapshot_date'].max() < today:
        g = pd.concat([g, pd.DataFrame([{'snapshot_date': today, 'valore': pf['value_now'].sum(),
                                         'versato': pf['cost'].sum()}])])
    if len(g) < 2:
        return
    st.subheader("Andamento")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=g['snapshot_date'], y=g['versato'], name='Versato', line=dict(color='#9E9E9E', dash='dot')))
    fig.add_trace(go.Scatter(x=g['snapshot_date'], y=g['valore'], name='Valore', mode='lines+markers',
                             line=dict(color='#1565C0', width=3)))
    fig.update_layout(height=300, yaxis_title='€', hovermode='x unified', legend=dict(orientation='h', y=-0.2))
    st.plotly_chart(fig, use_container_width=True)


# --------------------------------------------------------------------------
def _where_is_money(dm, pf):
    st.subheader("Dove sono i tuoi soldi")
    rules = dm.rules_engine.rules
    archived = set(rules.get('archived_accounts') or [])
    df = dm.get_transactions()
    df['date'] = pd.to_datetime(df['date'])
    now = df[df['date'] <= pd.Timestamp(datetime.date.today())]
    bal = now.groupby('account')['amount'].sum()
    parts = {}
    for a, v in bal.items():
        if a in VIRTUAL_ACCOUNTS or a in archived or abs(v) < 0.01:
            continue
        if a in INVESTMENT_ACCOUNTS:
            v = pf['value_now'].sum() if not pf.empty else v
        parts[a] = float(v)
    tot = sum(parts.values())
    if not tot:
        return
    fig = px.bar(x=list(parts.values()), y=list(parts.keys()), orientation='h',
                 text=[f"€{v:,.0f} ({v / tot * 100:.0f}%)" for v in parts.values()])
    fig.update_layout(height=60 + 45 * len(parts), margin=dict(t=10, b=10), xaxis_title='€', yaxis_title='')
    st.plotly_chart(fig, use_container_width=True)
    avg_exp = avg_monthly(now)
    liquid = sum(v for a, v in parts.items() if a not in INVESTMENT_ACCOUNTS)
    target = int(rules.get('emergency_target_months', 6) or 6)
    if avg_exp:
        st.caption(f"Soldi non investiti: €{liquid:,.0f} = {liquid / avg_exp:.1f} mesi di spese "
                   f"(spesa media €{avg_exp:,.0f}/mese; il tuo obiettivo di fondo emergenza è {target} mesi).")


# --------------------------------------------------------------------------
def _learn(dm, pf):
    st.subheader("Capire come investire")
    rules = dm.rules_engine.rules
    st.markdown(
        "Principi generali (non è una consulenza personalizzata: per decidere cosa comprare serve un consulente "
        "indipendente):\n"
        "1. **Prima il fondo emergenza**: 3–6 mesi di spese in un conto risparmio, subito disponibile.\n"
        "2. **Soldi che ti servono entro 2–3 anni** (auto, viaggi, casa): conto risparmio o obbligazionario a breve, "
        "non in borsa.\n"
        "3. **Soldi per il lungo periodo (10+ anni)**: in genere si usano ETF azionari *globali* molto diversificati "
        "(migliaia di aziende in un solo prodotto), con versamenti regolari (piano di accumulo).\n"
        "4. **Singole azioni = rischio concentrato**: un'azienda può perdere il 40% anche quando il mercato tiene.\n"
        "5. **Costi bassi** e **niente movimenti di pancia**: i cali del 20–30% capitano e nel lungo periodo sono "
        "stati recuperati, ma solo da chi non ha venduto.\n"
        "6. **Fondo pensione di categoria (Cometa)**: versamenti deducibili e contributo del datore di lavoro.")
    if not pf.empty:
        pos = pf[~pf['is_cash']]
        single = pos[~pos['name'].map(_is_etf)]['value_now'].sum() / pos['value_now'].sum() * 100
        st.caption(f"Oggi il tuo portafoglio è per il {single:.0f}% in singole azioni.")

    st.markdown("#### Simulatore piano di accumulo")
    c1, c2, c3 = st.columns(3)
    monthly = c1.number_input("Versamento mensile €", 0, 5000, 100, step=25, key='pac_m')
    years = c2.slider("Anni", 1, 30, 10, key='pac_y')
    initial = c3.number_input("Capitale iniziale €", 0, 500000, 0, step=500, key='pac_i')
    from src.utils import savings_accounts
    savings_rate = float(next(iter(savings_accounts(rules).values()), {'rate': 2.5})['rate'])
    scen = {f"Conto risparmio {savings_rate:.1f}%": savings_rate / 100,
            "Obbligazionario ~3%": 0.03, "Bilanciato ~5%": 0.05, "Azionario globale ~7%": 0.07}
    fig = go.Figure()
    res = []
    for name, r in scen.items():
        s = pac_projection(monthly, years, r, initial)
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=name, mode='lines'))
        res.append({'Scenario': name, f'Dopo {years} anni': f"€{s.iloc[-1]:,.0f}"})
    versato = initial + monthly * 12 * years
    fig.add_trace(go.Scatter(x=list(range(1, years + 1)), y=[initial + monthly * 12 * y for y in range(1, years + 1)],
                             name='Versato', line=dict(color='#9E9E9E', dash='dot')))
    fig.update_layout(height=320, xaxis_title='Anni', yaxis_title='€', hovermode='x unified',
                      legend=dict(orientation='h', y=-0.25))
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(pd.DataFrame(res), hide_index=True, use_container_width=True)
    st.caption(f"Versato in totale €{versato:,.0f}. Rendimenti medi ipotetici e costanti: nella realtà variano "
               "molto anno per anno (l'azionario globale ha avuto anni a −30% e anni a +30%) e non sono garantiti. "
               "Il conto risparmio è l'unico con rendimento quasi certo (finché il tasso non cambia).")
