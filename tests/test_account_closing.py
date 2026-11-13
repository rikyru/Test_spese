"""Test della chiusura conti: piano delle operazioni e registrazione."""
import datetime
import pandas as pd
import pytest
from src.account_closing import plan_closing, apply_closing
from tests.test_data_manager import dm, insert_transaction  # noqa: F401

MAIN = 'Portafoglio'


def test_plan_with_real_numbers_keeps_total_and_matches_each_account():
    app = {'Conto BNL': -3322.44, MAIN: 9309.96, 'Risparmi Revolut': 4623.50}
    real = {'Conto BNL': 2189.76, MAIN: 4783.98, 'Risparmi Revolut': 3673.00}
    ops = plan_closing(app, real, MAIN, first=True)
    gap = [o for o in ops if o['kind'] == 'adjustment'][0]
    assert gap['account'] == MAIN and gap['amount'] == pytest.approx(sum(real.values()) - sum(app.values()))
    after = dict(app)
    after[MAIN] += gap['amount']
    for o in ops:
        if o['kind'] == 'transfer':
            after[o['from']] -= o['amount']
            after[o['to']] += o['amount']
            assert o['amount'] > 0
    for k in real:
        assert after[k] == pytest.approx(real[k])


def test_plan_untracked_spending_after_first_closing():
    ops = plan_closing({MAIN: 1000.0, 'MPS': 500.0}, {MAIN: 950.0, 'MPS': 500.0}, MAIN)
    assert ops == [{'kind': 'untracked', 'account': MAIN, 'amount': -50.0}]


def test_plan_nothing_when_equal():
    assert plan_closing({MAIN: 10.0}, {MAIN: 10.0}, MAIN) == []


def test_apply_closing_only_adds_rows_and_aligns(dm):
    dm.rules_engine.rules = {}
    d0 = datetime.date(2025, 1, 10)
    insert_transaction(dm, d0, 1000.0, 'stipendio', account=MAIN, type_='Income', category='Stipendio')
    insert_transaction(dm, d0, -300.0, 'mutuo', account='MPS', type_='Expense', category='Casa')
    before = dm.get_transactions()
    real = {MAIN: 400.0, 'MPS': 250.0}
    app = dm.get_account_balances()
    today = datetime.date(2026, 11, 13)
    apply_closing(dm, plan_closing(app, real, MAIN), today)
    bal = dm.get_account_balances()
    assert bal[MAIN] == pytest.approx(400.0) and bal['MPS'] == pytest.approx(250.0)
    after = dm.get_transactions()
    old = after[pd.to_datetime(after['date']) == pd.Timestamp(d0)]
    assert len(old) == len(before)                          # storico intatto
    new = after[pd.to_datetime(after['date']) == pd.Timestamp(today)]
    untracked = new[new['category'] == 'Non registrate']
    assert untracked['amount'].sum() == pytest.approx(-50.0)  # 650 reali vs 700 in app


def test_archived_accounts_hidden_from_selectors(dm):
    insert_transaction(dm, datetime.date(2025, 1, 1), 10.0, 'x', account='Vecchio', type_='Income')
    insert_transaction(dm, datetime.date(2025, 1, 1), 10.0, 'x', account=MAIN, type_='Income')
    dm.rules_engine.rules = {'archived_accounts': ['Vecchio']}
    assert dm.get_unique_accounts(include_archived=False) == [MAIN]
    assert 'Vecchio' in dm.get_unique_accounts()


def test_investments_valued_not_untracked_and_card_subtracted():
    from src.account_closing import group_real
    neg = {'Carta di credito da addebitare'}
    real_main = group_real(['Unicredit', 'Carta di credito da addebitare'],
                           {'Unicredit': 1000.0, 'Carta di credito da addebitare': 68.22}, neg)
    assert real_main == pytest.approx(931.78)
    ops = plan_closing({MAIN: 931.78, 'Inv': 240.0}, {MAIN: 931.78, 'Inv': 200.0}, MAIN, investments={'Inv'})
    assert ops == [{'kind': 'valuation', 'account': 'Inv', 'amount': -40.0}]


def test_liquid_balance_excludes_investments():
    from src.utils import liquid_balance
    df = pd.DataFrame({'account': ['Conto', 'Investimenti Revolut', 'Partner'], 'amount': [100.0, 200.0, -50.0]})
    assert liquid_balance(df) == 100.0


def test_accrued_interest_and_closing_interest_op():
    from src.utils import accrued_interest
    assert accrued_interest(3433.0, 2.5, 0.0, 365) == pytest.approx(85.825)
    assert accrued_interest(3433.0, 2.5, 26.0, 30) == pytest.approx(3433 * (1.025 ** (30 / 365) - 1) * 0.74)
    assert accrued_interest(-10.0, 2.5, 26.0, 30) == 0.0
    # salvadanaio cresciuto di 5€ con 5,2€ attesi → tutto interessi, niente trasferimenti né non registrate
    ops = plan_closing({MAIN: 1000.0, 'Ris': 3433.0}, {MAIN: 1000.0, 'Ris': 3438.0}, MAIN,
                       expected_interest={'Ris': 5.2})
    assert ops == [{'kind': 'interest', 'account': 'Ris', 'amount': 5.0}]
    # +200 con 5€ attesi: 7,5€ interessi (cap 1,5×), il resto è un trasferimento dal conto principale
    ops = plan_closing({MAIN: 1000.0, 'Ris': 3433.0}, {MAIN: 800.0, 'Ris': 3633.0}, MAIN,
                       expected_interest={'Ris': 5.0})
    kinds = [o['kind'] for o in ops]
    assert ops[0] == {'kind': 'interest', 'account': 'Ris', 'amount': 7.5}
    assert 'untracked' in kinds and 'transfer' in kinds
