"""Calcoli condivisi su entrate/spese (nessuna UI): definizioni uniche usate da tutta l'app."""
import calendar
import pandas as pd
import numpy as np
from src.utils import SUBSCRIPTION_TAGS
from src.partner_share import my_share_view


# ---------------------------------------------------------------------------
# HELPER: entrate/spese REALI (esclude trasferimenti interni, saldo iniziale,
# aggiustamenti di saldo). Questi movimenti falsano tasso di risparmio,
# entrate, confronto YoY e income analysis se contati come entrate/spese.
# ---------------------------------------------------------------------------
_INTERNAL_CATEGORIES = {'trasferimento', 'transfer', 'initial balance',
                        'adjustment', 'saldo iniziale'}


_INTERNAL_TYPES = {'incoming transfer', 'outgoing transfer', 'transfer', 'adjustment'}


def _internal_mask(df):
    """True per righe che sono trasferimenti interni / saldo iniziale / aggiustamenti."""
    if df.empty:
        return pd.Series([], dtype=bool)
    cat = df['category'].astype('string').fillna('').str.strip().str.lower()
    typ = df['type'].astype('string').fillna('').str.strip().str.lower()
    desc = df['description'].astype('string').fillna('').str.lower()
    return (cat.isin(_INTERNAL_CATEGORIES) | typ.isin(_INTERNAL_TYPES)
            | desc.str.contains('saldo iniziale', na=False))


def real_income(df):
    """Entrate reali: type 'Income' escludendo trasferimenti/saldi/aggiustamenti."""
    if df.empty:
        return df.copy()
    return df[(df['type'] == 'Income') & (~_internal_mask(df))].copy()


def real_expenses(df):
    """Spese reali: type 'Expense' escludendo trasferimenti/saldi/aggiustamenti."""
    if df.empty:
        return df.copy()
    return df[(df['type'] == 'Expense') & (~_internal_mask(df))].copy()


def _tags_list(t):
    """Normalizza la colonna tags (list/ndarray/None) in una lista Python."""
    if hasattr(t, 'tolist'):
        t = t.tolist()
    return t if isinstance(t, list) else []


def _is_subscription(tags):
    """True se la transazione ha un tag di servizio in abbonamento."""
    return any(str(x).lower() in SUBSCRIPTION_TAGS for x in _tags_list(tags))


# --- Accuratezza: mese parziale, freschezza dati, entrate straordinarie ---
EXTRAORDINARY_INCOME_CATS = {'regali', 'entrate aggiuntive', 'rimborsi', 'rimborso', 'bonus'}


def in_progress_period(df):
    """
    Periodo mensile ancora IN CORSO (mese odierno non ancora concluso e con dati),
    altrimenti None. Serve a escludere il mese parziale dalle medie/proiezioni.
    """
    if df.empty:
        return None
    today = pd.Timestamp.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    if today.day >= last_day:
        return None
    cur = pd.Period(today, freq='M')
    d = pd.to_datetime(df['date'])
    return cur if (d.dt.to_period('M') == cur).any() else None


def drop_in_progress(monthly_series, df):
    """Rimuove il mese in corso (parziale) da una serie mensile (indice Period o Timestamp)."""
    ip = in_progress_period(df)
    if ip is None or monthly_series.empty:
        return monthly_series
    try:
        as_period = pd.PeriodIndex(pd.to_datetime(monthly_series.index.to_timestamp()
                                   if hasattr(monthly_series.index, 'to_timestamp')
                                   else monthly_series.index), freq='M')
    except Exception:
        as_period = pd.PeriodIndex([pd.Period(x, freq='M') for x in monthly_series.index], freq='M')
    return monthly_series[as_period != ip]


# Base UNICA per le medie mensili mostrate nelle analisi: ultimi 12 mesi
# completi (mese in corso escluso), contando anche i mesi a zero.
AVG_WINDOW_MONTHS = 12


AVG_BASIS_NOTE = "Media degli ultimi 12 mesi completi (mese in corso escluso)"


def last_complete_period(df):
    """Ultimo mese concluso con dati (il mese in corso parziale non conta)."""
    if df is None or df.empty:
        return None
    ip = in_progress_period(df)
    return ip - 1 if ip is not None else pd.to_datetime(df['date']).max().to_period('M')


def monthly_totals(df, kind='expense', ref_df=None):
    """Totali mensili (positivi) di spese o entrate reali sui mesi COMPLETI,
    con i mesi senza movimenti a 0. `ref_df` (default `df`) decide qual è
    l'ultimo mese completo: serve quando `df` è un sottoinsieme (es. una categoria)."""
    ref = df if ref_df is None else ref_df
    end = last_complete_period(ref)
    sub = real_expenses(df) if kind == 'expense' else real_income(df)
    if end is None or sub.empty:
        return pd.Series(dtype=float)
    s = sub.groupby(pd.to_datetime(sub['date']).dt.to_period('M'))['amount'].sum()
    s = s.abs() if kind == 'expense' else s
    start = s.index.min()
    if start > end:
        return pd.Series(dtype=float)
    return s.reindex(pd.period_range(start, end, freq='M'), fill_value=0.0)


def avg_monthly(df, kind='expense', ref_df=None, window=AVG_WINDOW_MONTHS):
    """Media mensile standard (vedi AVG_BASIS_NOTE)."""
    s = monthly_totals(df, kind, ref_df).tail(window)
    return float(s.mean()) if len(s) else 0.0


def comparable_prev_month(df, year, month, today=None):
    """Mese precedente confrontabile con (year, month). Se il mese scelto è quello
    in corso, il precedente viene troncato allo stesso giorno (1–oggi), altrimenti
    un mese parziale sembrerebbe sempre 'in calo'. Ritorna (df_precedente, etichetta)."""
    today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
    prev = pd.Period(year=year, month=month, freq='M') - 1
    d = pd.to_datetime(df['date'])
    out = df[d.dt.to_period('M') == prev]
    if (year, month) == (today.year, today.month) and \
            today.day < calendar.monthrange(today.year, today.month)[1]:
        out = out[pd.to_datetime(out['date']).dt.day <= today.day]
        return out, f"vs 1–{today.day} {MONTH_ABBR[prev.month]}"
    return out, f"vs {MONTH_ABBR[prev.month]}"


MONTH_ABBR = {1: "gen", 2: "feb", 3: "mar", 4: "apr", 5: "mag", 6: "giu",
              7: "lug", 8: "ago", 9: "set", 10: "ott", 11: "nov", 12: "dic"}


def spending_forecast(monthly, window=AVG_WINDOW_MONTHS, backtest_months=18):
    """Previsione onesta della spesa del prossimo mese da una serie di mesi
    COMPLETI: media degli ultimi `window` mesi, intervallo tipico (10°–90°
    percentile) e errore medio che questo stesso metodo avrebbe avuto sugli
    ultimi `backtest_months` mesi (ognuno previsto solo coi dati precedenti)."""
    s = monthly.dropna()
    if len(s) < 3:
        return None
    last = s.tail(window)
    errs = []
    for i in range(max(len(s) - backtest_months, 3), len(s)):
        hist = s.iloc[:i].tail(window)
        errs.append(abs(hist.mean() - s.iloc[i]))
    prev = s.iloc[:-window].tail(window) if len(s) > window else pd.Series(dtype=float)
    return {
        'expected': float(last.mean()),
        'low': float(last.quantile(0.10)), 'high': float(last.quantile(0.90)),
        'mae': float(np.mean(errs)) if errs else None,
        'mae_pct': float(np.mean(errs) / last.mean() * 100) if errs and last.mean() else None,
        'trend_pct': float((last.mean() / prev.mean() - 1) * 100) if len(prev) >= 6 and prev.mean() else None,
        'n': len(last),
    }


def typical_income(df, window=AVG_WINDOW_MONTHS):
    """Entrata TIPICA mensile: mediana degli ultimi `window` mesi completi (robusta a
    tredicesima, regali, rimborsi 730). Unica definizione usata in tutta l'app."""
    s = monthly_totals(df, 'income').tail(window)
    return float(s.median()) if len(s) else 0.0


def category_overview(df, ref_df=None, today=None, window=AVG_WINDOW_MONTHS):
    """Per categoria di spesa reale: media mensile sugli ultimi `window` mesi completi
    (mesi a zero inclusi), in quanti mesi c'è stata spesa, ultimo mese completo e
    mese in corso finora. Stessa base per Previsioni e Smart Insights."""
    ref = df if ref_df is None else ref_df
    exp = real_expenses(df)
    end = last_complete_period(ref)
    if exp.empty or end is None:
        return pd.DataFrame()
    exp = exp.assign(p=pd.to_datetime(exp['date']).dt.to_period('M'), a=exp['amount'].abs())
    months = pd.period_range(end - window + 1, end, freq='M')
    ip = in_progress_period(ref)
    rows = []
    for cat, g in exp.groupby('category'):
        by_m = g.groupby('p')['a'].sum().reindex(months, fill_value=0.0)
        now = float(g.loc[g['p'] == ip, 'a'].sum()) if ip is not None else 0.0
        if by_m.sum() == 0 and now == 0:
            continue
        rows.append({'categoria': cat, 'media': float(by_m.mean()), 'mesi_con_spesa': int((by_m > 0).sum()),
                     'ultimo': float(by_m.iloc[-1]), 'mese_in_corso': now})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out['n_mesi'] = len(months)
    out['scarto_ultimo'] = out['ultimo'] - out['media']
    return out.sort_values('media', ascending=False).reset_index(drop=True)


def thirteenth_estimate(data_manager):
    """Netto dell'ultima tredicesima dalle buste caricate (0 se non disponibile)."""
    try:
        ps = data_manager.get_payslips()
        t = ps[ps['kind'] == 'tredicesima'].sort_values('year')
        return float(t['netto'].iloc[-1]) if not t.empty else 0.0
    except Exception:
        return 0.0


SALARY_CATEGORY = 'Stipendio'


def salary_coverage(df, split_conf):
    """Per ogni mese COMPLETO: stipendio, tue spese (spese condivise alla tua
    quota stimata con le regole di Spese Condivise) e saldo = stipendio − spese."""
    end = last_complete_period(df)
    if end is None:
        return pd.DataFrame(columns=['stipendio', 'mie_spese', 'saldo'])
    inc = real_income(df)
    sal = inc[inc['category'] == SALARY_CATEGORY]
    exp = real_expenses(my_share_view(df, split_conf))
    per = lambda d: pd.to_datetime(d['date']).dt.to_period('M')
    out = pd.DataFrame({'stipendio': sal.groupby(per(sal))['amount'].sum(),
                        'mie_spese': exp.groupby(per(exp))['amount'].sum().abs()}).fillna(0.0)
    if out.empty:
        return pd.DataFrame(columns=['stipendio', 'mie_spese', 'saldo'])
    out = out.reindex(pd.period_range(out.index.min(), end, freq='M'), fill_value=0.0)
    out['saldo'] = out['stipendio'] - out['mie_spese']
    return out


def split_income(inc_df):
    """Divide le entrate reali in (ordinarie, straordinarie) per categoria."""
    if inc_df is None or inc_df.empty:
        return inc_df, inc_df
    cat = inc_df['category'].astype('string').fillna('').str.strip().str.lower()
    extra = cat.isin(EXTRAORDINARY_INCOME_CATS)
    return inc_df[~extra], inc_df[extra]
