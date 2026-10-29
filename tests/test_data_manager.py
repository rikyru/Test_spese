import pytest
import datetime
import pandas as pd
import duckdb
from unittest.mock import patch, MagicMock
from src.data_manager import DataManager


@pytest.fixture
def dm(tmp_path):
    """DataManager backed by an in-memory DuckDB and no rules file."""
    db_file = str(tmp_path / "test.duckdb")
    with patch('src.data_manager.RulesEngine') as MockRules:
        mock_engine = MagicMock()
        mock_engine.apply_rules.side_effect = lambda df: df
        mock_engine.apply_history_rules.side_effect = lambda df: df
        mock_engine.auto_tag_from_description.side_effect = lambda df: df
        mock_engine.learn_from_history.return_value = {}
        MockRules.return_value = mock_engine
        manager = DataManager(db_path=db_file)
    return manager


def insert_transaction(dm, date, amount, description, category='Test', account='Conto', type_='Expense', tags=None):
    """Helper to insert a transaction directly."""
    if tags is None:
        tags = []
    dm.con.execute(
        "INSERT INTO transactions (date, amount, currency, account, category, tags, description, type, source_file, necessity, id) "
        "VALUES (?, ?, 'EUR', ?, ?, ?, ?, ?, 'manual', 'Want', uuid())",
        [date, amount, account, category, tags, description, type_]
    )


class TestSetupDb:
    def test_tables_created(self, dm):
        tables = dm.con.execute("SHOW TABLES").fetchall()
        table_names = [t[0] for t in tables]
        assert 'transactions' in table_names
        assert 'recurring_expenses' in table_names

    def test_transactions_columns(self, dm):
        cols = dm.con.execute("PRAGMA table_info(transactions)").fetchall()
        col_names = [c[1] for c in cols]
        for expected in ['date', 'amount', 'currency', 'account', 'category', 'tags', 'description', 'type', 'necessity', 'id']:
            assert expected in col_names


class TestGetTransactions:
    def test_empty_returns_dataframe(self, dm):
        df = dm.get_transactions()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_returns_inserted_rows(self, dm):
        insert_transaction(dm, datetime.date(2025, 1, 15), -50.0, 'Spesa Coop')
        insert_transaction(dm, datetime.date(2025, 1, 16), -20.0, 'Taxi')
        df = dm.get_transactions()
        assert len(df) == 2

    def test_ordered_by_date_desc(self, dm):
        insert_transaction(dm, datetime.date(2025, 1, 1), -10.0, 'Prima')
        insert_transaction(dm, datetime.date(2025, 3, 1), -20.0, 'Ultima')
        df = dm.get_transactions()
        assert df.iloc[0]['description'] == 'Ultima'
        assert df.iloc[1]['description'] == 'Prima'


class TestInitialBalance:
    def test_set_and_get_initial_balance(self, dm):
        dm.set_initial_balance(datetime.date(2025, 1, 1), 1000.0)
        result = dm.get_initial_balance()
        assert result is not None
        assert result['amount'] == 1000.0

    def test_update_initial_balance(self, dm):
        dm.set_initial_balance(datetime.date(2025, 1, 1), 1000.0)
        dm.set_initial_balance(datetime.date(2025, 1, 1), 2000.0)
        result = dm.get_initial_balance()
        assert result['amount'] == 2000.0

    def test_no_initial_balance_returns_none(self, dm):
        result = dm.get_initial_balance()
        assert result is None

    def test_initial_balance_type_is_income(self, dm):
        dm.set_initial_balance(datetime.date(2025, 1, 1), 500.0)
        df = dm.get_transactions()
        row = df[df['description'] == 'Saldo Iniziale']
        assert len(row) == 1
        assert row.iloc[0]['type'] == 'Income'


class TestRecurring:
    def test_add_and_get_recurring(self, dm):
        dm.add_recurring('Affitto', 800.0, 'Housing', 'Conto', 'Monthly',
                         datetime.date(2025, 2, 1), 'Affitto mensile', ['affitto'])
        df = dm.get_recurring()
        assert len(df) == 1
        assert df.iloc[0]['name'] == 'Affitto'
        assert df.iloc[0]['amount'] == 800.0

    def test_delete_recurring(self, dm):
        dm.add_recurring('Netflix', 13.99, 'Subscriptions', 'Conto', 'Monthly',
                         datetime.date(2025, 2, 1), '', [])
        df = dm.get_recurring()
        rec_id = df.iloc[0]['id']
        dm.delete_recurring(rec_id)
        assert len(dm.get_recurring()) == 0

    def test_update_recurring(self, dm):
        dm.add_recurring('Netflix', 13.99, 'Subscriptions', 'Conto', 'Monthly',
                         datetime.date(2025, 2, 1), '', [])
        df = dm.get_recurring()
        rec_id = df.iloc[0]['id']
        dm.update_recurring(rec_id, amount=15.99)
        updated = dm.get_recurring()
        assert updated.iloc[0]['amount'] == 15.99

    def test_process_recurring_creates_transaction(self, dm):
        past_date = datetime.date.today() - datetime.timedelta(days=1)
        dm.add_recurring('Affitto', 800.0, 'Housing', 'Conto', 'Monthly',
                         past_date, 'Affitto', [])
        count = dm.process_recurring()
        assert count == 1
        df = dm.get_transactions()
        assert len(df) == 1
        assert df.iloc[0]['amount'] == 800.0

    def test_process_recurring_advances_next_date(self, dm):
        past_date = datetime.date(2025, 1, 15)
        dm.add_recurring('Affitto', 800.0, 'Housing', 'Conto', 'Monthly',
                         past_date, 'Affitto', [])
        dm.process_recurring()
        df = dm.get_recurring()
        # next_date should advance by 1 month
        next_d = pd.to_datetime(df.iloc[0]['next_date']).date()
        assert next_d == datetime.date(2025, 2, 15)

    def test_process_recurring_future_not_processed(self, dm):
        future_date = datetime.date.today() + datetime.timedelta(days=10)
        dm.add_recurring('Netflix', 13.99, 'Subscriptions', 'Conto', 'Monthly',
                         future_date, '', [])
        count = dm.process_recurring()
        assert count == 0
        assert len(dm.get_transactions()) == 0

    def test_process_recurring_adds_recurring_tag(self, dm):
        past_date = datetime.date.today() - datetime.timedelta(days=1)
        dm.add_recurring('Spotify', 9.99, 'Subscriptions', 'Conto', 'Monthly',
                         past_date, '', [])
        dm.process_recurring()
        df = dm.get_transactions()
        tags = df.iloc[0]['tags']
        if hasattr(tags, 'tolist'):
            tags = tags.tolist()
        assert 'Recurring' in tags

    def test_process_recurring_installments_decrement(self, dm):
        past_date = datetime.date.today() - datetime.timedelta(days=1)
        dm.add_recurring('Rata', 100.0, 'Loan', 'Conto', 'Monthly',
                         past_date, '', [], installments=3)
        dm.process_recurring()
        df = dm.get_recurring()
        assert df.iloc[0]['remaining_installments'] == 2

    def test_process_recurring_last_installment_deletes(self, dm):
        past_date = datetime.date.today() - datetime.timedelta(days=1)
        dm.add_recurring('Rata Finale', 100.0, 'Loan', 'Conto', 'Monthly',
                         past_date, '', [], installments=1)
        dm.process_recurring()
        assert len(dm.get_recurring()) == 0


class TestGetProjectedRecurring:
    def test_projects_monthly_occurrences(self, dm):
        start = datetime.date.today()
        end = start + datetime.timedelta(days=65)
        dm.add_recurring('Affitto', 800.0, 'Housing', 'Conto', 'Monthly',
                         start, '', [])
        df = dm.get_projected_recurring(end)
        # Should have ~2-3 occurrences depending on days
        assert len(df) >= 2

    def test_empty_if_no_recurring(self, dm):
        end = datetime.date.today() + datetime.timedelta(days=30)
        df = dm.get_projected_recurring(end)
        assert df.empty

    def test_respects_end_date_limit(self, dm):
        start = datetime.date.today()
        rule_end = start + datetime.timedelta(days=15)
        projection_end = start + datetime.timedelta(days=60)
        dm.add_recurring('Abbonamento', 10.0, 'Sub', 'Conto', 'Monthly',
                         start, '', [], end_date=rule_end)
        df = dm.get_projected_recurring(projection_end)
        # All occurrences must be <= rule_end
        for _, row in df.iterrows():
            assert pd.to_datetime(row['date']).date() <= rule_end


class TestUpdateTag:
    def test_rename_tag(self, dm):
        insert_transaction(dm, datetime.date(2025, 1, 1), -10.0, 'Test', tags=['oldtag'])
        ok, _ = dm.update_tag('oldtag', 'newtag')
        assert ok
        df = dm.get_transactions()
        tags = df.iloc[0]['tags']
        if hasattr(tags, 'tolist'):
            tags = tags.tolist()
        assert 'newtag' in tags
        assert 'oldtag' not in tags

    def test_delete_tag(self, dm):
        insert_transaction(dm, datetime.date(2025, 1, 1), -10.0, 'Test', tags=['deltag'])
        ok, _ = dm.update_tag('deltag', None)
        assert ok
        df = dm.get_transactions()
        tags = df.iloc[0]['tags']
        if hasattr(tags, 'tolist'):
            tags = tags.tolist()
        assert 'deltag' not in tags

    def test_rename_nonexistent_tag_no_error(self, dm):
        insert_transaction(dm, datetime.date(2025, 1, 1), -10.0, 'Test', tags=['other'])
        ok, _ = dm.update_tag('ghost', 'new')
        assert ok  # No rows updated, but no error


class TestGetSummary:
    def test_summary_groups_by_month(self, dm):
        insert_transaction(dm, datetime.date(2025, 1, 10), -100.0, 'A', type_='Expense')
        insert_transaction(dm, datetime.date(2025, 1, 20), -50.0, 'B', type_='Expense')
        insert_transaction(dm, datetime.date(2025, 2, 5), 500.0, 'Stipendio', type_='Income')
        df = dm.get_summary()
        jan_expense = df[(df['year'] == 2025) & (df['month'] == 1) & (df['type'] == 'Expense')]
        assert not jan_expense.empty
        assert jan_expense.iloc[0]['total'] == pytest.approx(-150.0)

    def test_summary_empty_db(self, dm):
        df = dm.get_summary()
        assert df.empty
