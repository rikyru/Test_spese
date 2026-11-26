"""
Investimenti: lettura dello screenshot Revolut, prezzi di mercato aggiornati,
valore del portafoglio e simulatore di piano di accumulo. Nessuna UI qui.
"""
import json
import re
import urllib.request

import numpy as np
import pandas as pd

_NUM = r'\d{1,3}(?:\.\d{3})*,\d+|\d+'


def _num(s):
    return float(s.replace('.', '').replace(',', '.'))


def _rows(items, tol=12):
    """Raggruppa i testi OCR (bbox, testo, conf) in righe per coordinata y."""
    pts = sorted(((sum(p[1] for p in b) / 4, min(p[0] for p in b), t, b) for b, t, _ in items))
    rows, cur, y0 = [], [], None
    for y, x, t, b in pts:
        if y0 is None or abs(y - y0) <= tol:
            cur.append((x, t, b))
            y0 = y if y0 is None else (y0 + y) / 2
        else:
            rows.append(sorted(cur))
            cur, y0 = [(x, t, b)], y
    if cur:
        rows.append(sorted(cur))
    return rows


def _is_red(image, bbox):
    """True se il testo nel riquadro è rosso (andamento negativo su Revolut)."""
    if image is None:
        return None
    xs = [int(p[0]) for p in bbox]
    ys = [int(p[1]) for p in bbox]
    crop = np.asarray(image)[max(min(ys), 0):max(ys), max(min(xs), 0):max(xs), :3].astype(int)
    if crop.size == 0:
        return None
    px = crop.reshape(-1, 3)
    vivid = px[(px.max(axis=1) - px.min(axis=1)) > 60]          # solo pixel colorati (non sfondo/grigi)
    if len(vivid) < 5:
        return None
    return bool((vivid[:, 0] > vivid[:, 1]).mean() > 0.5)


def parse_revolut_screenshot(items, image=None):
    """Da OCR della schermata 'Conto di intermediazione' di Revolut a:
    {'total', 'total_pct', 'cash', 'positions': [{name, qty, symbol, price, currency, value, pct}]}.
    Il segno delle percentuali si ricava dal colore (rosso = negativo) se c'è l'immagine."""
    rows = _rows(items)
    out = {'total': None, 'total_pct': None, 'cash': 0.0, 'positions': []}
    pending = None
    for i, row in enumerate(rows):
        texts = [t for _, t, _ in row]
        line = ' '.join(texts)
        if out['total'] is None and re.search(r'intermediazione', line, re.I) and i + 1 < len(rows):
            nxt = rows[i + 1]
            for _, t, b in nxt:
                if '%' in t:
                    out['total_pct'] = _num(re.search(_NUM, t).group()) * (-1 if _is_red(image, b) else 1)
                elif '€' in t:
                    out['total'] = _num(re.search(_NUM, t).group())
            continue
        if re.search(r'saldo disponibile', line, re.I):
            m = re.search(r'(' + _NUM + r')\s*€', line)
            out['cash'] = _num(m.group(1)) if m else 0.0
            continue
        detail = re.search(r'(' + _NUM + r')\s+([A-Z][A-Z0-9.]{1,7})\s*[.·•]?\s*(' + _NUM + r')\s*([€$£])', line)
        if detail and pending:
            pct_b = [(t, b) for _, t, b in row if '%' in t]
            pct = _num(re.search(_NUM, pct_b[0][0]).group()) if pct_b else None
            if pct is not None and _is_red(image, pct_b[0][1]):
                pct = -pct
            pending.update({'qty': _num(detail.group(1)), 'symbol': detail.group(2),
                            'price': _num(detail.group(3)),
                            'currency': {'€': 'EUR', '$': 'USD', '£': 'GBP'}[detail.group(4)], 'pct': pct,
                            # Revolut mostra sempre 2 decimali: senza virgola l'OCR ha perso cifre
                            'pct_ok': bool(pct_b) and ',' in pct_b[0][0]})
            out['positions'].append(pending)
            pending = None
            continue
        # riga nome + valore a destra (es. "STMicroelectronics N.V   67,87 €")
        vals = [t for _, t, _ in row if re.fullmatch(r'\s*(' + _NUM + r')\s*€\s*', t)]
        names = [t for _, t, _ in row if re.search(r'[A-Za-z]{3}', t) and '€' not in t]
        if vals and names and len(row) >= 2:
            pending = {'name': ' '.join(names).strip(), 'value': _num(re.search(_NUM, vals[-1]).group())}
    return out


def guess_yahoo(symbol, currency):
    """Ticker Yahoo dal simbolo Revolut: titoli in € → borsa tedesca (Xetra), in $ → USA."""
    if not symbol:
        return ''
    return symbol if currency == 'USD' else f"{symbol}.DE"


def fetch_quote(yahoo, timeout=10):
    """Ultimo prezzo da Yahoo Finance: (prezzo, valuta) oppure (None, None)."""
    try:
        req = urllib.request.Request(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo}?range=5d&interval=1d",
            headers={'User-Agent': 'Mozilla/5.0'})
        meta = json.load(urllib.request.urlopen(req, timeout=timeout))['chart']['result'][0]['meta']
        return float(meta['regularMarketPrice']), meta.get('currency')
    except Exception:
        return None, None


def to_eur(price, currency, fx):
    """fx: valuta → quante unità per 1 EUR (es. {'USD': 1.10})."""
    if price is None:
        return None
    if currency in (None, 'EUR'):
        return price
    rate = fx.get(currency)
    return price / rate if rate else None


def portfolio_value(holdings, quotes, fx):
    """Valore di oggi per posizione. holdings: DataFrame dell'ultima fotografia
    (name, yahoo, qty, value, cost, is_cash). quotes: yahoo → (prezzo, valuta).
    Se manca il prezzo si usa il valore della fotografia."""
    h = holdings.copy()
    live = []
    for _, r in h.iterrows():
        if r.get('is_cash'):
            live.append(r['value'])
            continue
        p, cur = quotes.get(r['yahoo'], (None, None))
        v = to_eur(p, cur, fx)
        live.append(v * r['qty'] if v is not None else r['value'])
    h['value_now'] = live
    h['gain'] = h['value_now'] - h['cost']
    h['gain_pct'] = np.where(h['cost'] > 0, h['gain'] / h['cost'] * 100, 0.0)
    tot = h['value_now'].sum()
    h['weight'] = h['value_now'] / tot * 100 if tot else 0.0
    return h


def pac_projection(monthly, years, annual_rate, initial=0.0):
    """Piano di accumulo: valore a fine di ogni anno con rendimento annuo costante
    (capitalizzazione mensile). Ritorna Series anno → valore."""
    r = (1 + annual_rate) ** (1 / 12) - 1
    v, out = float(initial), {}
    for m in range(1, int(years) * 12 + 1):
        v = v * (1 + r) + monthly
        if m % 12 == 0:
            out[m // 12] = v
    return pd.Series(out)


def implied_cost(value, pct):
    """Somma versata da valore attuale e rendimento % (es. 90 a −10% → 100)."""
    return value / (1 + pct / 100) if pct is not None and pct > -100 else value


def reconcile_with_total(parsed, tol=1.0):
    """Se il versato totale implicito (totale e % del conto) non torna con la somma
    dei versati delle posizioni, corregge l'unica % letta male dall'OCR (spesso
    perde cifre: '9,42%' → '42%', riconoscibile perché senza decimali).
    Segna la posizione con 'fixed': True."""
    if parsed.get('total') is None or parsed.get('total_pct') is None:
        return parsed
    target = implied_cost(parsed['total'], parsed['total_pct']) - parsed.get('cash', 0.0)
    pos = parsed['positions']
    costs = [implied_cost(p['value'], p.get('pct')) for p in pos]
    if abs(sum(costs) - target) <= tol:
        return parsed
    suspects = [i for i, p in enumerate(pos) if not p.get('pct_ok', True)]
    if len(suspects) != 1:
        return parsed
    i = suspects[0]
    need = target - sum(c for j, c in enumerate(costs) if j != i)
    if need > 0:
        new_pct = round((pos[i]['value'] / need - 1) * 100, 2)
        if -95 < new_pct < 500:
            pos[i]['pct'], pos[i]['fixed'] = new_pct, True
    return parsed


def latest_snapshot(dm, account):
    s = dm.get_investment_snapshots(account)
    if s.empty:
        return s
    return s[s['snapshot_date'] == s['snapshot_date'].max()].reset_index(drop=True)


def live_portfolio(dm, account, max_age_hours=6, fetch=True):
    """Ultima fotografia del portafoglio valorizzata ai prezzi di oggi (cache di
    `max_age_hours` ore). Ritorna (DataFrame posizioni, data fotografia) o (vuoto, None)."""
    snap = latest_snapshot(dm, account)
    if snap.empty:
        return snap, None
    quotes = dm.get_cached_prices(max_age_hours)
    need = [y for y in snap.loc[~snap['is_cash'], 'yahoo'].dropna().unique() if y and y not in quotes]
    currencies = set(snap['currency'].dropna()) - {'EUR'}
    need += [f"EUR{c}=X" for c in currencies if f"EUR{c}=X" not in quotes]
    if fetch:
        for y in need:
            p, c = fetch_quote(y, timeout=6)
            if p is not None:
                dm.cache_price(y, p, c)
                quotes[y] = (p, c)
    fx = {c: quotes[f"EUR{c}=X"][0] for c in currencies if f"EUR{c}=X" in quotes}
    return portfolio_value(snap, quotes, fx), pd.to_datetime(snap['snapshot_date'].iloc[0])


def search_ticker(query, timeout=8):
    """Cerca un titolo per nome su Yahoo: lista di (ticker, nome, borsa), solo azioni/ETF."""
    import urllib.parse
    try:
        req = urllib.request.Request(
            "https://query1.finance.yahoo.com/v1/finance/search?q="
            f"{urllib.parse.quote(query)}&quotesCount=8&newsCount=0", headers={'User-Agent': 'Mozilla/5.0'})
        quotes = json.load(urllib.request.urlopen(req, timeout=timeout)).get('quotes', [])
    except Exception:
        return []
    return [(q['symbol'], q.get('shortname') or q.get('longname') or q['symbol'], q.get('exchange', ''))
            for q in quotes if q.get('quoteType') in ('EQUITY', 'ETF')]


def price_in_eur(yahoo, quotes_fn=fetch_quote):
    """Prezzo attuale in euro di un ticker: (prezzo_eur, prezzo, valuta) o (None, None, None)."""
    p, cur = quotes_fn(yahoo)
    if p is None:
        return None, None, None
    if cur in (None, 'EUR'):
        return p, p, cur or 'EUR'
    fx, _ = quotes_fn(f"EUR{cur}=X")
    return (p / fx if fx else None), p, cur


def add_purchase(dm, account, name, yahoo, amount, date, from_account=None, qty=None, price_eur=None,
                 currency='EUR'):
    """Registra un acquisto: aggiunge (o incrementa) la posizione nell'ultima fotografia
    del portafoglio — nuova fotografia datata `date` — e, se `from_account`, il
    trasferimento dei soldi verso il conto investimenti. Se il pagamento arriva dalla
    liquidità del conto di intermediazione (from_account=None) la scala da lì.
    Ritorna la quantità registrata."""
    if qty is None:
        if not price_eur:
            raise ValueError("Serve la quantità o il prezzo in euro")
        qty = amount / price_eur
    snap = latest_snapshot(dm, account)
    snap = snap.drop(columns=[c for c in ('snapshot_date', 'account', 'created_at') if c in snap.columns])
    positions = snap.astype(object).where(snap.notna(), None).to_dict('records') if not snap.empty else []
    for p in positions:
        p['is_cash'] = bool(p.get('is_cash'))
    existing = next((p for p in positions if not p['is_cash'] and p.get('yahoo') == yahoo), None)
    if existing:
        existing['qty'] = (existing.get('qty') or 0) + qty
        existing['cost'] = (existing.get('cost') or 0) + amount
        existing['value'] = (existing.get('value') or 0) + amount
    else:
        positions.append({'name': name, 'symbol': yahoo.split('.')[0], 'yahoo': yahoo, 'qty': qty,
                          'price': amount / qty if qty else None, 'currency': currency,
                          'value': amount, 'pct': 0.0, 'cost': amount, 'is_cash': False})
    if from_account is None:
        cash = next((p for p in positions if p['is_cash']), None)
        if cash is None or (cash.get('value') or 0) < amount - 0.01:
            raise ValueError("Liquidità del conto investimenti insufficiente")
        cash['value'] -= amount
        cash['cost'] = cash['value']
    dm.save_investment_snapshot(date, account, positions)
    if from_account:
        dm.add_transfer(from_account, account, amount, date, description=f"Acquisto {name}",
                        tag='investimento', source='investment_buy')
    return qty


def _positions(snap):
    snap = snap.drop(columns=[c for c in ('snapshot_date', 'account', 'created_at') if c in snap.columns])
    positions = snap.astype(object).where(snap.notna(), None).to_dict('records') if not snap.empty else []
    for p in positions:
        p['is_cash'] = bool(p.get('is_cash'))
    return positions


def align_ledger(dm, account, date, total, description):
    """Porta il saldo del conto investimenti nell'app al valore `total` alla data,
    con una variazione di valore (neutra per le analisi). Ritorna la variazione."""
    from src.utils import INVESTMENT_CATEGORY
    bal = float(dm.con.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account = ? "
                               "AND date <= ?", [account, date]).fetchone()[0])
    diff = round(total - bal, 2)
    if abs(diff) >= 0.01:
        dm.con.execute("""
            INSERT INTO transactions (id, date, amount, currency, account, category, tags, description,
                                      type, source_file, original_description)
            VALUES (uuid(), ?, ?, 'EUR', ?, ?, ['investimenti'], ?, 'Adjustment', 'investments', ?)
        """, [date, diff, account, INVESTMENT_CATEGORY, description, description])
    return diff


def add_sale(dm, account, yahoo, qty, proceeds, date, to_account=None):
    """Registra una vendita: toglie `qty` quote del titolo dall'ultima fotografia
    (costo ridotto in proporzione, a costo medio) e mette l'incasso nella liquidità
    del conto di intermediazione oppure, se `to_account`, lo trasferisce lì.
    Il saldo del conto investimenti nell'app si allinea al nuovo valore del
    portafoglio (variazione neutra). Ritorna dict qty, costo venduto, plusvalenza."""
    snap = latest_snapshot(dm, account)
    if snap.empty:
        raise ValueError("Nessuna posizione registrata nel portafoglio")
    last = pd.to_datetime(snap['snapshot_date'].iloc[0]).date()
    date = pd.to_datetime(date).date()
    if date < last:
        raise ValueError(f"La data è precedente all'ultima fotografia del portafoglio ({last:%d/%m/%Y})")
    positions = _positions(snap)
    pos = next((p for p in positions if not p['is_cash'] and p.get('yahoo') == yahoo), None)
    if pos is None:
        raise ValueError(f"{yahoo} non è nel portafoglio")
    held = float(pos.get('qty') or 0)
    if qty > held + 1e-6:
        raise ValueError(f"Hai solo {held:.4f} quote di {pos['name']}")
    share = min(qty / held, 1.0) if held else 1.0
    cost_sold = float(pos.get('cost') or 0) * share
    if share >= 1.0 - 1e-6:
        positions.remove(pos)
    else:
        pos['qty'] = held - qty
        pos['cost'] = float(pos.get('cost') or 0) - cost_sold
        pos['value'] = float(pos.get('value') or 0) * (1 - share)
    if to_account is None:
        cash = next((p for p in positions if p['is_cash']), None)
        if cash is None:
            cash = {'name': 'Liquidità', 'value': 0.0, 'cost': 0.0, 'is_cash': True, 'currency': 'EUR'}
            positions.append(cash)
        cash['value'] = float(cash.get('value') or 0) + proceeds
        cash['cost'] = cash['value']
    dm.save_investment_snapshot(date, account, positions)
    gain = proceeds - cost_sold
    total = sum(float(p.get('value') or 0) for p in positions)
    if to_account:
        dm.add_transfer(account, to_account, proceeds, date, description=f"Vendita {pos['name']}",
                        tag='investimento', source='investment_sell')
    align_ledger(dm, account, date, total, f"Vendita {pos['name']} ({gain:+.2f}€ realizzati)")
    return {'qty': qty, 'cost_sold': cost_sold, 'gain': gain, 'name': pos['name']}
