import pytest
import pandas as pd
from unittest.mock import patch, mock_open
from src.rules_engine import RulesEngine


SAMPLE_RULES = {
    'categories': [
        {'name': 'Groceries', 'match': ['coop', 'conad', 'carrefour'], 'necessity': 'Need'},
        {'name': 'Subscriptions', 'match': ['netflix', 'spotify'], 'necessity': 'Want'},
        {'name': 'Transport', 'match': ['uber', 'taxi']},
    ],
    'tags': [
        {'tag': 'subscription', 'match': ['netflix', 'spotify']},
        {'tag': 'food', 'match': ['coop', 'conad', 'pizza']},
    ]
}


@pytest.fixture
def engine():
    """RulesEngine with no file on disk — returns empty rules gracefully."""
    with patch.object(RulesEngine, 'load_rules', return_value=SAMPLE_RULES):
        e = RulesEngine(rules_path="/nonexistent/rules.yaml")
        e.rules = SAMPLE_RULES
    return e


@pytest.fixture
def empty_engine():
    """RulesEngine with empty rules."""
    with patch.object(RulesEngine, 'load_rules', return_value={'categories': [], 'tags': []}):
        e = RulesEngine(rules_path="/nonexistent/rules.yaml")
        e.rules = {'categories': [], 'tags': []}
    return e


def make_df(descriptions):
    return pd.DataFrame({
        'description': descriptions,
        'category': [None] * len(descriptions),
        'tags': [[] for _ in descriptions],
        'necessity': ['Want'] * len(descriptions),
    })


class TestApplyRules:
    def test_category_assigned(self, engine):
        df = make_df(['Pagamento COOP supermercato'])
        result = engine.apply_rules(df)
        assert result.iloc[0]['category'] == 'Groceries'

    def test_category_case_insensitive(self, engine):
        df = make_df(['NETFLIX abbonamento'])
        result = engine.apply_rules(df)
        assert result.iloc[0]['category'] == 'Subscriptions'

    def test_necessity_assigned(self, engine):
        df = make_df(['spesa CONAD'])
        result = engine.apply_rules(df)
        assert result.iloc[0]['necessity'] == 'Need'

    def test_no_match_leaves_category_none(self, engine):
        df = make_df(['descrizione sconosciuta'])
        result = engine.apply_rules(df)
        assert result.iloc[0]['category'] is None

    def test_empty_dataframe(self, engine):
        df = pd.DataFrame()
        result = engine.apply_rules(df)
        assert result.empty

    def test_tag_appended(self, engine):
        df = make_df(['Netflix mensile'])
        result = engine.apply_rules(df)
        assert 'subscription' in result.iloc[0]['tags']

    def test_multiple_tags_no_duplicates(self, engine):
        df = make_df(['Coop spesa'])
        result = engine.apply_rules(df)
        tags = result.iloc[0]['tags']
        assert tags.count('food') == 1

    def test_multiple_rows(self, engine):
        df = make_df(['COOP', 'Spotify', 'Ristorante ignoto'])
        result = engine.apply_rules(df)
        assert result.iloc[0]['category'] == 'Groceries'
        assert result.iloc[1]['category'] == 'Subscriptions'
        assert result.iloc[2]['category'] is None

    def test_empty_rules(self, empty_engine):
        df = make_df(['Netflix', 'COOP'])
        result = empty_engine.apply_rules(df)
        assert result.iloc[0]['category'] is None
        assert result.iloc[1]['category'] is None


class TestAutoTagFromDescription:
    def test_luce_tagged(self, engine):
        df = make_df(['Bolletta LUCE Enel'])
        result = engine.auto_tag_from_description(df)
        assert 'luce' in result.iloc[0]['tags']

    def test_amazon_tagged(self, engine):
        df = make_df(['Amazon acquisto'])
        result = engine.auto_tag_from_description(df)
        assert 'amazon' in result.iloc[0]['tags']

    def test_no_keyword_no_tag(self, engine):
        df = make_df(['Ristorante da Mario'])
        result = engine.auto_tag_from_description(df)
        assert result.iloc[0]['tags'] == []

    def test_no_duplicate_tag(self, engine):
        df = make_df(['Uber corsa'])
        df.at[0, 'tags'] = ['uber']
        result = engine.auto_tag_from_description(df)
        assert result.iloc[0]['tags'].count('uber') == 1


class TestLearnFromHistory:
    def test_builds_lookup(self, engine):
        hist = pd.DataFrame({
            'description': ['Netflix', 'Netflix', 'Coop'],
            'category': ['Subscriptions', 'Subscriptions', 'Groceries'],
        })
        lookup = engine.learn_from_history(hist)
        assert lookup['netflix'] == 'Subscriptions'
        assert lookup['coop'] == 'Groceries'

    def test_empty_history(self, engine):
        lookup = engine.learn_from_history(pd.DataFrame({'description': [], 'category': []}))
        assert lookup == {}

    def test_mode_wins_on_conflict(self, engine):
        hist = pd.DataFrame({
            'description': ['Uber', 'Uber', 'Uber'],
            'category': ['Transport', 'Transport', 'Other'],
        })
        lookup = engine.learn_from_history(hist)
        assert lookup['uber'] == 'Transport'

    def test_ignores_null_categories(self, engine):
        hist = pd.DataFrame({
            'description': ['Foo', 'Foo'],
            'category': [None, None],
        })
        lookup = engine.learn_from_history(hist)
        assert 'foo' not in lookup


class TestApplyHistoryRules:
    def test_fills_missing_category(self, engine):
        engine.history_lookup = {'netflix': 'Subscriptions'}
        df = make_df(['Netflix'])
        df.at[0, 'category'] = None
        result = engine.apply_history_rules(df)
        assert result.iloc[0]['category'] == 'Subscriptions'

    def test_does_not_overwrite_existing(self, engine):
        engine.history_lookup = {'netflix': 'Subscriptions'}
        df = make_df(['Netflix'])
        df.at[0, 'category'] = 'Entertainment'
        result = engine.apply_history_rules(df)
        assert result.iloc[0]['category'] == 'Entertainment'

    def test_no_lookup_returns_unchanged(self, engine):
        if hasattr(engine, 'history_lookup'):
            del engine.history_lookup
        df = make_df(['Netflix'])
        result = engine.apply_history_rules(df)
        assert result.iloc[0]['category'] is None
