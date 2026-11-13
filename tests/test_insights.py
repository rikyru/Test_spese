"""Test di rate, stagionalità, qualità dati e resoconto mese."""
import datetime
import pandas as pd
import pytest
from src.insights import (installments_overview, seasonal_index, unmatched_transfers,
                          negative_accounts, stale_accounts, possible_duplicates)


def test_installments_overview_plan_and_end():
    rec = pd.DataFrame([
        {'name': 'Tablet', 'amount': -60.0, 'frequency': 'Monthly', 'next_date': datetime.date(2026, 12, 6),
         'remaining_installments': 3, 'installments_total': 4},
        {'name': 'Bici', 'amount': -40.0, 'frequency': 'Monthly', 'next_date': datetime.date(2026, 11, 28),
         'remaining_installments': 1, 'installments_total': 1},
        {'name': 'Mutuo', 'amount': -390.0, 'frequency': 'Monthly', 'next_date': datetime.date(2026, 11, 28),
         'remaining_installments': None, 'installments_total': None},
    ])
    rows, plan = installments_overview(rec)
    assert list(rows['nome']) == ['Bici', 'Tablet']
    assert rows.set_index('nome').loc['Tablet', 'ultima'] == datetime.date(2027, 2, 6)
    assert plan[pd.Period('2026-11', 'M')] == 40.0 and plan[pd.Period('2027-02', 'M')] == 60.0
    assert rows.set_index('nome').loc['Tablet', 'residuo'] == 180.0
    assert bool(rows.set_index('nome').loc['Bici', 'nuova'])


def test_seasonal_index_detects_peak_and_needs_history():
    idx = pd.period_range('2022-01', periods=36, freq='M')
    s = pd.Series([2000.0 if p.month == 12 else 1000.0 for p in idx], index=idx)
    si = seasonal_index(s, shrink=0.0)
    assert si.loc[12, 'indice'] > 1.5 and si.loc[6, 'indice'] < 1.0
    short = seasonal_index(s.tail(12))
    assert (short['indice'] == 1.0).all()


def _df(rows):
    return pd.DataFrame(rows, columns=['date', 'account', 'type', 'amount', 'description', 'category', 'source_file'])


def test_unmatched_transfers():
    df = _df([
        ('2026-01-01', 'A', 'Outgoing Transfer', -100.0, 'x', None, ''),
        ('2026-01-02', 'B', 'Incoming Transfer', 100.0, 'x', None, ''),
        ('2026-02-01', 'A', 'Outgoing Transfer', -50.0, 'y', None, ''),     # senza controparte
    ])
    u = unmatched_transfers(df)
    assert list(u['amount']) == [-50.0]


def test_negative_and_stale_accounts():
    df = _df([
        ('2025-01-01', 'BNL', 'Income', 100.0, '', 'X', ''),
        ('2026-01-01', 'BNL', 'Expense', -390.0, '', 'Casa', ''),
        ('2020-01-01', 'Vecchio', 'Income', 50.0, '', 'X', ''),
        ('2026-01-01', 'Partner', 'Expense', -80.0, '', 'X', ''),
    ])
    neg = negative_accounts(df, virtual={'Partner'})
    assert list(neg['conto']) == ['BNL'] and neg['saldo'].iloc[0] == -290.0
    st_ = stale_accounts(df, days=45, today='2026-11-01', virtual={'Partner'})
    assert set(st_['conto']) == {'BNL', 'Vecchio'}


def test_possible_duplicates_ignores_recurring():
    df = _df([
        ('2026-01-01', 'A', 'Expense', -10.0, 'bar', 'X', 'csv'),
        ('2026-01-01', 'A', 'Expense', -10.0, 'bar', 'X', 'csv'),
        ('2026-01-05', 'A', 'Expense', -5.0, 'rata', 'X', 'Recurring'),
        ('2026-01-05', 'A', 'Expense', -5.0, 'rata', 'X', 'Recurring'),
    ])
    df['tags'] = [['bar'], ['bar'], [], []]
    assert len(possible_duplicates(df)) == 2
    df.loc[1, 'tags'] = ['pizza']
    assert possible_duplicates(df).empty


def test_month_summary_compares_with_previous_12_months():
    from src.ui.month_report import month_summary
    rows = []
    for m in range(1, 13):
        rows.append((f'2025-{m:02d}-05', 'C', 'Expense', -1000.0, 'spesa', 'Spesa', 'csv'))
        rows.append((f'2025-{m:02d}-27', 'C', 'Income', 2000.0, 'stip', 'Stipendio', 'csv'))
    rows.append(('2026-01-05', 'C', 'Expense', -1500.0, 'spesa', 'Spesa', 'csv'))
    rows.append(('2026-01-27', 'C', 'Income', 2000.0, 'stip', 'Stipendio', 'csv'))
    df = _df(rows)
    df['tags'] = [[] for _ in range(len(df))]
    df['necessity'] = 'Need'
    s = month_summary(df, pd.Period('2026-01', 'M'), {}, {'excluded': [], 'monthly': 600, 'enabled': True})
    assert s['spent'] == 1500.0 and s['avg12'] == 1000.0 and s['same_last_year'] == 1000.0
    cat = s['cats'].set_index('categoria').loc['Spesa']
    assert cat['media'] == 1000.0 and cat['scarto'] == 500.0
    assert s['salary']['saldo'] == 500.0


# --- Investimenti ---
def _ocr_item(x, y, text, w=100, h=18):
    return ([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], text, 0.9)


def test_parse_revolut_screenshot_and_reconcile():
    from src.investments import parse_revolut_screenshot, reconcile_with_total
    items = [_ocr_item(87, 352, 'Conto di intermediazione'), _ocr_item(87, 375, '199,99 €'), _ocr_item(161, 375, '17,39%'),
             _ocr_item(84, 436, 'Saldo disponibile'), _ocr_item(337, 439, '1,12 €'),
             _ocr_item(85, 503, 'STMicroelectronics N.V'), _ocr_item(323, 503, '67,87 €'),
             _ocr_item(85, 525, '1,62 SGM . 41,78 €'), _ocr_item(337, 525, '9,51%'),
             _ocr_item(85, 579, 'Knorr-Bremse AG'), _ocr_item(321, 579, '52,57 €'),
             _ocr_item(85, 601, '0,53 KBX . 99,10 €'), _ocr_item(347, 601, '42%'),
             _ocr_item(84, 654, 'L&G Cyber Security Acc ETF'), _ocr_item(321, 655, '45,37 €'),
             _ocr_item(85, 677, '1,1 USPY'), _ocr_item(157, 679, '40,91 €'), _ocr_item(333, 677, '9,26%'),
             _ocr_item(84, 728, 'Ionq'), _ocr_item(319, 731, '33,06 €'),
             _ocr_item(85, 753, '1,27 IONQ . 28,74 $'), _ocr_item(327, 755, '42,94%')]
    p = parse_revolut_screenshot(items)          # senza immagine: segno non ricavabile → positivo
    assert p['total'] == 199.99 and p['cash'] == 1.12 and len(p['positions']) == 4
    syms = [x['symbol'] for x in p['positions']]
    assert syms == ['SGM', 'KBX', 'USPY', 'IONQ']
    assert p['positions'][3]['currency'] == 'USD' and p['positions'][0]['qty'] == 1.62
    # con i segni (come dal colore rosso) e la % di KBX letta male
    p['total_pct'] = -17.39
    for x in p['positions']:
        x['pct'] = -abs(x['pct'])
    r = reconcile_with_total(p)
    kbx = r['positions'][1]
    assert kbx.get('fixed') and kbx['pct'] == pytest.approx(-9.4, abs=0.05)
    assert r['positions'][3]['pct'] == -42.94


def test_portfolio_value_and_pac():
    from src.investments import portfolio_value, pac_projection, guess_yahoo
    h = pd.DataFrame([{'name': 'A', 'yahoo': 'A.DE', 'qty': 2.0, 'value': 100.0, 'cost': 120.0, 'is_cash': False},
                      {'name': 'B', 'yahoo': 'B', 'qty': 1.0, 'value': 50.0, 'cost': 40.0, 'is_cash': False},
                      {'name': 'Liquidità', 'yahoo': None, 'qty': None, 'value': 5.0, 'cost': 5.0, 'is_cash': True}])
    pv = portfolio_value(h, {'A.DE': (60.0, 'EUR'), 'B': (110.0, 'USD')}, {'USD': 1.1})
    assert list(pv['value_now']) == pytest.approx([120.0, 100.0, 5.0])
    assert pv.loc[0, 'gain'] == pytest.approx(0.0) and pv.loc[1, 'gain_pct'] == pytest.approx(150.0)
    assert guess_yahoo('KBX', 'EUR') == 'KBX.DE' and guess_yahoo('IONQ', 'USD') == 'IONQ'
    s = pac_projection(100, 2, 0.0)
    assert list(s) == [1200.0, 2400.0]
    assert pac_projection(100, 1, 0.05).iloc[-1] > 1200
