"""
Logica (senza UI) per: rate attive, stagionalità delle spese e controlli di
qualità dei dati. Usata da Dashboard e Analisi.
"""
import pandas as pd

from src.data_manager import advance_date


# --------------------------------------------------------------------------
# RATE
# --------------------------------------------------------------------------
def installments_overview(rec_df, today=None):
    """Rate attive (ricorrenti con rate rimanenti). Ritorna (righe, piano mensile):
    righe = nome, importo, rimaste/totali, prossima e ultima scadenza, residuo;
    piano = Series mese → totale rate in uscita."""
    today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
    if rec_df is None or rec_df.empty or 'remaining_installments' not in rec_df:
        return pd.DataFrame(), pd.Series(dtype=float)
    r = rec_df[rec_df['remaining_installments'].notna()].copy()
    if r.empty:
        return pd.DataFrame(), pd.Series(dtype=float)
    rows, plan = [], {}
    for _, x in r.iterrows():
        left = int(x['remaining_installments'])
        amt = abs(float(x['amount']))
        d = pd.to_datetime(x['next_date']).date()
        dates = []
        for _ in range(left):
            dates.append(d)
            d = advance_date(d, x['frequency'])
        for dd in dates:
            p = pd.Period(dd, freq='M')
            plan[p] = plan.get(p, 0.0) + amt
        total = x.get('installments_total')
        total = int(total) if pd.notna(total) else None
        rows.append({'nome': x['name'], 'importo': amt, 'rimaste': left, 'totali': total,
                     'prossima': dates[0], 'ultima': dates[-1], 'residuo': amt * left,
                     'nuova': total is not None and total - left <= 1})
    out = pd.DataFrame(rows).sort_values('ultima').reset_index(drop=True)
    return out, pd.Series(plan).sort_index()


# --------------------------------------------------------------------------
# STAGIONALITÀ
# --------------------------------------------------------------------------
def seasonal_index(monthly, min_years=2, shrink=0.5):
    """Indice stagionale per mese di calendario (1–12): rapporto tra la spesa del
    mese e la media dei 12 mesi centrati intorno, mediano sugli anni disponibili,
    'ristretto' verso 1 (shrink) per non inseguire eventi singoli. Ritorna
    DataFrame mese → indice, n_anni (indice 1 se meno di `min_years` anni)."""
    s = monthly.dropna()
    if len(s) < 24:
        return pd.DataFrame({'indice': [1.0] * 12, 'n_anni': [0] * 12}, index=range(1, 13))
    base = s.rolling(12, center=True, min_periods=12).mean()
    ratio = (s / base).dropna()
    rows = []
    for m in range(1, 13):
        r = ratio[[p.month == m for p in ratio.index]]
        if len(r) >= min_years:
            idx = 1 + (float(r.median()) - 1) * (1 - shrink)
        else:
            idx = 1.0
        rows.append({'indice': idx, 'n_anni': len(r)})
    return pd.DataFrame(rows, index=range(1, 13))


# --------------------------------------------------------------------------
# QUALITÀ DEI DATI
# --------------------------------------------------------------------------
TRANSFER_TYPES = {'Outgoing Transfer', 'Incoming Transfer'}


def unmatched_transfers(df, days=3):
    """Trasferimenti senza la 'gamba' opposta (stesso importo, entro `days` giorni,
    su un altro conto)."""
    t = df[df['type'].isin(TRANSFER_TYPES)].copy()
    if t.empty:
        return t
    t['date'] = pd.to_datetime(t['date'])
    t['abs'] = t['amount'].abs().round(2)
    out_ = t[t['type'] == 'Outgoing Transfer']
    in_ = t[t['type'] == 'Incoming Transfer']
    used = set()
    unmatched = []
    for i, r in out_.iterrows():
        cand = in_[(in_['abs'] == r['abs']) & (in_['account'] != r['account'])
                   & ((in_['date'] - r['date']).abs().dt.days <= days) & (~in_.index.isin(used))]
        if cand.empty:
            unmatched.append(i)
        else:
            used.add(cand.index[0])
    unmatched += [i for i in in_.index if i not in used]
    return t.loc[unmatched].sort_values('date')


def negative_accounts(df, virtual=()):
    """Conti reali con saldo attuale negativo: saldo, da quando è negativo e
    andamento annuo (utile a capire cosa manca)."""
    rows = []
    for acc, g in df[~df['account'].isin(virtual)].groupby('account'):
        g = g.sort_values('date')
        bal = float(g['amount'].sum())
        if bal >= -1:
            continue
        run = g['amount'].cumsum()
        pos = run[run >= 0]
        since = pd.to_datetime(g.loc[pos.index[-1], 'date']) if len(pos) else pd.to_datetime(g['date'].iloc[0])
        by_year = g.groupby(pd.to_datetime(g['date']).dt.year)['amount'].sum().round(0).to_dict()
        rows.append({'conto': acc, 'saldo': bal, 'negativo_dal': since, 'per_anno': by_year})
    return pd.DataFrame(rows)


def recurring_on_account(rec_df, account):
    """Ricorrenti addebitate su un conto (per spiegare un saldo che scende da solo)."""
    if rec_df is None or rec_df.empty:
        return pd.DataFrame()
    return rec_df[rec_df['account'] == account]


def stale_accounts(df, days=45, today=None, virtual=()):
    """Conti con saldo non nullo e nessun movimento da più di `days` giorni."""
    today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
    rows = []
    for acc, g in df[~df['account'].isin(virtual)].groupby('account'):
        last = pd.to_datetime(g['date']).max()
        bal = float(g['amount'].sum())
        if (today - last).days > days and abs(bal) > 1:
            rows.append({'conto': acc, 'ultimo_movimento': last, 'saldo': bal})
    return pd.DataFrame(rows)


def possible_duplicates(df):
    """Spese con stessa data, importo, conto, descrizione, categoria e tag (escluse le ricorrenti)."""
    e = df[df['type'] == 'Expense'].copy()
    if 'source_file' in e:
        e = e[e['source_file'] != 'Recurring']
    e['description'] = e['description'].fillna('')
    # anche categoria e tag: due spese senza descrizione e con lo stesso importo
    # ma di categoria/tag diversi (es. pizza e cinesi) non sono doppioni
    e['_tags'] = e['tags'].apply(lambda t: ','.join(sorted(map(str, t.tolist() if hasattr(t, 'tolist') else (t or [])))))
    key = ['date', 'amount', 'account', 'description', 'category', '_tags']
    d = e[e.duplicated(key, keep=False)]
    return d.sort_values(key).drop(columns='_tags')


def untagged_or_unclassified(df):
    """Spese senza tag e spese senza classificazione Necessità/Desiderio."""
    e = df[df['type'] == 'Expense']

    def _no_tags(t):
        if hasattr(t, 'tolist'):
            t = t.tolist()
        return not (isinstance(t, list) and any(str(x) not in ('', 'Recurring', 'nan') for x in t))
    no_tags = e[e['tags'].apply(_no_tags)]
    no_nec = e[~e['necessity'].isin(['Need', 'Want'])] if 'necessity' in e else e.iloc[0:0]
    return no_tags, no_nec


# --------------------------------------------------------------------------
# IMPEGNI DEL MESE ("safe to spend")
# --------------------------------------------------------------------------
def month_commitments(dm, df, today=None):
    """Spese già note che devono ancora uscire entro fine mese: ricorrenti e rate
    non ancora addebitate, movimenti registrati con data futura (es. bollette
    importate con la scadenza) e spese in programma. Ritorna DataFrame
    voce, data, importo (positivo), tipo."""
    import calendar
    import datetime
    today = pd.Timestamp(today or datetime.date.today()).normalize()
    end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    rows = []
    try:
        pr = dm.get_projected_recurring(end.date())
        for _, r in pr.iterrows():
            if r['amount'] < 0:
                rows.append({'voce': r['name'], 'data': pd.to_datetime(r['date']), 'importo': abs(r['amount']),
                             'tipo': 'Ricorrente'})
    except Exception:
        pass
    d = pd.to_datetime(df['date'])
    fut = df[(d > today) & (d <= end) & (df['type'] == 'Expense')]
    for _, r in fut.iterrows():
        rows.append({'voce': r['description'] or r['category'], 'data': pd.to_datetime(r['date']),
                     'importo': abs(r['amount']), 'tipo': 'Già registrata (data futura)'})
    try:
        pl = dm.get_planned()
        pl = pl[(pd.to_datetime(pl['due_date']) > today) & (pd.to_datetime(pl['due_date']) <= end)]
        for _, r in pl.iterrows():
            rows.append({'voce': r['name'], 'data': pd.to_datetime(r['due_date']), 'importo': abs(r['amount']),
                         'tipo': 'In programma'})
    except Exception:
        pass
    out = pd.DataFrame(rows, columns=['voce', 'data', 'importo', 'tipo'])
    return out.sort_values('data').reset_index(drop=True)


def month_outlook(df, commitments, typical_variable, typical_salary, today=None, salary_category='Stipendio'):
    """Il mese in corso con gli impegni noti. Ritorna dict con:
    entrate, speso, impegni, stipendio_atteso (se lo stipendio non è ancora arrivato),
    disponibile (= entrate + stipendio atteso − speso − impegni),
    variabile_restante (spesa variabile tipica che manca a fine mese) e
    risparmio_previsto (= disponibile − variabile_restante)."""
    import datetime
    from src.metrics import real_income, real_expenses
    today = pd.Timestamp(today or datetime.date.today()).normalize()
    d = pd.to_datetime(df['date'])
    month = df[(d.dt.to_period('M') == today.to_period('M')) & (d <= today)]
    inc = real_income(month)
    exp = real_expenses(month)
    entrate = float(inc['amount'].sum())
    speso = float(exp['amount'].abs().sum())
    stip_atteso = 0.0 if (inc['category'] == salary_category).any() else float(typical_salary or 0.0)
    impegni = float(commitments['importo'].sum()) if not commitments.empty else 0.0
    var_spent = float(exp[exp.get('source_file', pd.Series(index=exp.index, dtype=object)) != 'Recurring']['amount']
                      .abs().sum()) if not exp.empty else 0.0
    var_rest = max(float(typical_variable or 0.0) - var_spent, 0.0)
    disponibile = entrate + stip_atteso - speso - impegni
    return {'entrate': entrate, 'speso': speso, 'impegni': impegni, 'stipendio_atteso': stip_atteso,
            'disponibile': disponibile, 'variabile_restante': var_rest,
            'risparmio_previsto': disponibile - var_rest}
