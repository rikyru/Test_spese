"""Test della logica finanziaria critica: liquidità vs conti virtuali, entrate/spese
reali, mese in corso, prestiti, spese pagate dal partner e ricorrenti."""
import datetime
import pandas as pd
import pytest
from unittest.mock import patch

from src.utils import VIRTUAL_ACCOUNTS, liquid_balance
from src.data_manager import advance_date
from src.ui.analysis import real_income, real_expenses, in_progress_period, drop_in_progress
from tests.test_data_manager import dm as _dm_fixture, insert_transaction  # noqa: F401


@pytest.fixture
def dm(_dm_fixture):
    # Il RulesEngine è mockato: regole vuote per _necessity_from_rules
    _dm_fixture.rules_engine.rules = {}
    return _dm_fixture


def _df(rows):
    return pd.DataFrame(rows, columns=['date', 'amount', 'account', 'category', 'type', 'description'])


class TestLiquidBalance:
    def test_excludes_virtual_accounts(self):
        df = _df([
            ('2025-01-01', 1000.0, 'Conto', 'Stipendio', 'Income', ''),
            ('2025-01-02', -200.0, 'Conto', 'Trasferimento', 'Outgoing Transfer', ''),
            ('2025-01-02', 200.0, 'Prestiti', 'Trasferimento', 'Incoming Transfer', ''),
            ('2025-01-03', -50.0, 'Partner', 'Spesa', 'Expense', ''),
        ])
        assert liquid_balance(df) == 800.0

    def test_empty_and_none(self):
        assert liquid_balance(None) == 0.0
        assert liquid_balance(_df([])) == 0.0

    def test_virtual_set(self):
        assert VIRTUAL_ACCOUNTS == {'Partner', 'Prestiti'}


class TestRealIncomeExpenses:
    def test_excludes_transfers_and_initial_balance(self):
        df = _df([
            ('2025-01-01', 2000.0, 'Conto', 'Stipendio', 'Income', 'Stipendio'),
            ('2025-01-01', 5000.0, 'Conto', 'Initial Balance', 'Income', 'Saldo Iniziale'),
            ('2025-01-02', 300.0, 'Conto', 'Trasferimento', 'Incoming Transfer', ''),
            ('2025-01-03', -80.0, 'Conto', 'Spesa', 'Expense', 'Coop'),
            ('2025-01-03', -300.0, 'Conto', 'Trasferimento', 'Expense', 'giroconto'),
            ('2025-01-04', -10.0, 'Conto', 'Adjustment', 'Expense', ''),
        ])
        assert real_income(df)['amount'].sum() == 2000.0
        assert real_expenses(df)['amount'].sum() == -80.0


class TestInProgressPeriod:
    def test_current_month_detected(self):
        today = pd.Timestamp.today()
        last_day = pd.Timestamp(today.year, today.month, 1) + pd.offsets.MonthEnd(0)
        df = _df([(today.normalize(), -1.0, 'Conto', 'X', 'Expense', '')])
        expected = None if today.day >= last_day.day else pd.Period(today, freq='M')
        assert in_progress_period(df) == expected

    def test_no_current_month_data(self):
        df = _df([('2020-01-15', -1.0, 'Conto', 'X', 'Expense', '')])
        assert in_progress_period(df) is None

    def test_drop_in_progress(self):
        today = pd.Timestamp.today()
        df = _df([(today.normalize(), -1.0, 'Conto', 'X', 'Expense', ''),
                  ('2020-01-15', -1.0, 'Conto', 'X', 'Expense', '')])
        s = pd.Series([10.0, 20.0], index=pd.PeriodIndex(['2020-01', pd.Period(today, freq='M')], freq='M'))
        out = drop_in_progress(s, df)
        if in_progress_period(df) is None:
            assert len(out) == 2
        else:
            assert list(out.index.astype(str)) == ['2020-01']


class TestAdvanceDate:
    @pytest.mark.parametrize('freq,expected', [
        ('Weekly', datetime.date(2025, 1, 8)),
        ('Monthly', datetime.date(2025, 2, 1)),
        ('Bimonthly', datetime.date(2025, 3, 1)),
        ('Quarterly', datetime.date(2025, 4, 1)),
        ('Yearly', datetime.date(2026, 1, 1)),
    ])
    def test_frequencies(self, freq, expected):
        assert advance_date(datetime.date(2025, 1, 1), freq) == expected

    def test_month_end_clamped(self):
        assert advance_date(datetime.date(2025, 1, 31), 'Monthly') == datetime.date(2025, 2, 28)


class TestLoans:
    def test_loan_moves_to_virtual_and_is_not_expense(self, dm):
        insert_transaction(dm, datetime.date(2025, 1, 1), 1000.0, 'Stipendio', category='Stipendio', type_='Income')
        assert dm.add_loan('Mario', 200, 'Conto', datetime.date(2025, 1, 5))
        df = dm.get_transactions()
        assert liquid_balance(df) == 800.0
        assert df[df['account'] == 'Prestiti']['amount'].sum() == 200.0
        assert real_expenses(df).empty
        assert real_income(df)['amount'].sum() == 1000.0

    def test_repay_restores_liquidity(self, dm):
        dm.add_loan('Mario', 200, 'Conto', datetime.date(2025, 1, 5))
        dm.repay_loan('Mario', 150, 'Conto', datetime.date(2025, 2, 5))
        df = dm.get_transactions()
        assert liquid_balance(df) == -50.0
        assert df[df['account'] == 'Prestiti']['amount'].sum() == 50.0

    def test_partner_loan_balance(self, dm):
        dm.add_loan('Cena', 100, 'Conto', datetime.date(2025, 1, 5), to_partner=True)
        dm.repay_loan('Cena', 40, 'Conto', datetime.date(2025, 1, 20), from_partner=True)
        assert dm.get_partner_loan_balance() == 60.0
        detail = dm.get_partner_loans_detail()
        assert set(detail['name']) == {'Cena'}


class TestPartnerPaidExpense:
    def test_only_my_share_on_partner_account(self, dm):
        mine = dm.add_partner_paid_expense('Spesa', 100, 'Spesa', datetime.date(2025, 1, 5), 40)
        assert mine == 40.0
        df = dm.get_transactions()
        assert len(df) == 1
        row = df.iloc[0]
        assert row['account'] == 'Partner' and row['amount'] == -40.0
        assert 'partner_paid' in list(row['tags'])
        # È una spesa reale ma non tocca la liquidità
        assert real_expenses(df)['amount'].sum() == -40.0
        assert liquid_balance(df) == 0.0

    def test_zero_share_inserts_nothing(self, dm):
        assert dm.add_partner_paid_expense('Spesa', 100, 'Spesa', datetime.date(2025, 1, 5), 0) == 0.0
        assert dm.get_transactions().empty


class TestRecurring:
    def _recs(self, dm):
        return dm.con.execute("SELECT * FROM recurring_expenses").df()

    def test_generates_with_template_tags(self, dm):
        start = datetime.date.today() - datetime.timedelta(days=1)
        dm.add_recurring('PC', -100.0, 'Tech', 'Conto', 'Monthly', start, 'PC a rate', ['pc', 'rate'], installments=5)
        assert dm.process_recurring() == 1
        tx = dm.get_transactions()
        assert len(tx) == 1
        assert set(tx.iloc[0]['tags']) == {'pc', 'rate', 'Recurring'}
        rec = self._recs(dm).iloc[0]
        assert rec['remaining_installments'] == 4
        assert rec['installments_total'] == 5
        assert pd.to_datetime(rec['next_date']).date() == advance_date(start, 'Monthly')

    def test_last_installment_removes_template(self, dm):
        start = datetime.date.today() - datetime.timedelta(days=1)
        dm.add_recurring('Ultima', -50.0, 'Tech', 'Conto', 'Monthly', start, '', [], installments=1)
        dm.process_recurring()
        assert self._recs(dm).empty
        assert len(dm.get_transactions()) == 1

    def test_end_date_removes_template(self, dm):
        start = datetime.date.today() - datetime.timedelta(days=1)
        dm.add_recurring('Fine', -10.0, 'X', 'Conto', 'Monthly', start, '', [], end_date=start)
        dm.process_recurring()
        assert self._recs(dm).empty

    def test_future_not_generated(self, dm):
        dm.add_recurring('Futura', -10.0, 'X', 'Conto', 'Monthly',
                         datetime.date.today() + datetime.timedelta(days=10), '', [])
        assert dm.process_recurring() == 0
        assert dm.get_transactions().empty


# --- Rimborsi del partner e media mensile standard ---
from src.reimbursements import net_partner_reimbursements, partner_share
from src.ui.analysis import monthly_totals, avg_monthly

SPLIT_CONF = {
    'default_share_pct': 50,
    'loan_tags': ['prestito'],
    'rules': [{'type': 'tag', 'match': 'luce', 'my_share': 50},
              {'type': 'category', 'match': 'Spesa alimentare', 'my_share': 70}],
}


def _tx(rows):
    """rows: (date, amount, category, type, tags)"""
    df = pd.DataFrame(rows, columns=['date', 'amount', 'category', 'type', 'tags'])
    df['date'] = pd.to_datetime(df['date'])
    df['account'] = 'Conto'
    df['description'] = ''
    return df


class TestPartnerShare:
    def test_rules(self):
        assert partner_share('Spesa alimentare', [], SPLIT_CONF) == pytest.approx(0.3)
        assert partner_share('Casa', ['luce'], SPLIT_CONF) == pytest.approx(0.5)
        assert partner_share('Casa', ['prestito'], SPLIT_CONF) == 1.0
        assert partner_share('Svago', [], SPLIT_CONF) == 0.0
        assert partner_share('Svago', ['condiviso'], SPLIT_CONF) == pytest.approx(0.5)
        assert partner_share('Spesa alimentare', ['partner_paid'], SPLIT_CONF) == 0.0


class TestNetReimbursements:
    def test_reimbursement_nets_previous_month_by_weight(self):
        df = _tx([
            ('2026-08-05', -100.0, 'Spesa alimentare', 'Expense', []),   # peso 30
            ('2026-08-10', -60.0, 'Casa', 'Expense', ['luce']),         # peso 30
            ('2026-08-12', -50.0, 'Svago', 'Expense', []),              # non condivisa
            ('2026-09-07', 40.0, 'Entrate aggiuntive', 'Income', ['rimborsocri']),
            ('2026-09-10', -80.0, 'Spesa alimentare', 'Expense', []),   # mese del rimborso: non toccato
        ])
        out = net_partner_reimbursements(df, SPLIT_CONF)
        assert out['amount'].sum() == pytest.approx(df['amount'].sum())
        assert out.loc[0, 'amount'] == pytest.approx(-80.0)
        assert out.loc[1, 'amount'] == pytest.approx(-40.0)
        assert out.loc[2, 'amount'] == -50.0
        assert out.loc[4, 'amount'] == -80.0
        assert out.loc[3, 'type'] == 'Reimbursement' and out.loc[3, 'amount'] == 0.0
        assert real_income(out).empty

    def test_actual_amount_wins_over_rules_but_never_positive(self):
        df = _tx([
            ('2026-08-05', -100.0, 'Spesa alimentare', 'Expense', []),   # regole: 30
            ('2026-09-07', 150.0, 'Entrate aggiuntive', 'Income', ['rimborsocri']),
        ])
        out = net_partner_reimbursements(df, SPLIT_CONF)
        assert out.loc[0, 'amount'] == pytest.approx(0.0)
        # eccedenza oltre la spesa resta entrata
        assert out.loc[1, 'type'] == 'Income' and out.loc[1, 'amount'] == pytest.approx(50.0)
        assert out['amount'].sum() == pytest.approx(df['amount'].sum())

    def test_falls_back_to_older_month(self):
        df = _tx([
            ('2026-06-05', -100.0, 'Spesa alimentare', 'Expense', []),
            ('2026-08-07', 20.0, 'Entrate aggiuntive', 'Income', ['rimborsocri']),
        ])
        out = net_partner_reimbursements(df, SPLIT_CONF)
        assert out.loc[0, 'amount'] == pytest.approx(-80.0)

    def test_no_reimbursements_unchanged(self):
        df = _tx([('2026-08-05', -100.0, 'Spesa alimentare', 'Expense', [])])
        out = net_partner_reimbursements(df, SPLIT_CONF)
        assert out['amount'].tolist() == [-100.0]


class TestMonthlyAverage:
    def test_zero_months_count_and_partial_excluded(self):
        df = _tx([
            ('2020-01-10', -120.0, 'X', 'Expense', []),
            ('2020-03-10', -60.0, 'X', 'Expense', []),
        ])
        s = monthly_totals(df)
        assert list(s.values) == [120.0, 0.0, 60.0]
        assert avg_monthly(df) == pytest.approx(60.0)
        assert avg_monthly(df, window=2) == pytest.approx(30.0)

    def test_subset_uses_reference_end(self):
        full = _tx([
            ('2020-01-10', -100.0, 'A', 'Expense', []),
            ('2020-04-10', -10.0, 'B', 'Expense', []),
        ])
        sub = full[full['category'] == 'A']
        assert len(monthly_totals(sub, ref_df=full)) == 4
        assert avg_monthly(sub, ref_df=full) == pytest.approx(25.0)
