import datetime
import pandas as pd
import pytest
from src.ui.wants_envelope import envelope_status, wants_by_month, envelope_config


def test_status_states():
    d = datetime.date(2026, 11, 15)          # metà mese (30 giorni)
    ok = envelope_status(250, 600, d)
    assert ok['state'] == 'ok' and ok['left'] == 350 and ok['days_left'] == 16
    assert ok['per_day'] == pytest.approx(350 / 16)
    assert envelope_status(400, 600, d)['state'] == 'veloce'
    over = envelope_status(700, 600, d)
    assert over['state'] == 'sforata' and over['per_day'] == 0


def test_wants_by_month_filters_and_shares():
    df = pd.DataFrame({
        'date': ['2026-11-02'] * 5,
        'amount': [-100.0, -50.0, -200.0, -80.0, 1000.0],
        'category': ['Mangiare e Bere', 'Spesa alimentare', 'Viaggi', 'Spesa alimentare', 'Stipendio'],
        'type': ['Expense'] * 4 + ['Income'],
        'necessity': ['Want', 'Need', 'Want', 'Want', None],
        'tags': [[], [], [], [], []],
        'account': ['Conto'] * 5, 'description': [''] * 5,
    })
    conf = {'rules': [{'type': 'category', 'match': 'Spesa alimentare', 'my_share': 50}]}
    e = wants_by_month(df, conf, ['Viaggi'])
    assert sorted(e['a'].tolist()) == [40.0, 100.0]     # 80 condivisa al 50%; Viaggi escluso


def test_config_defaults_and_override():
    assert envelope_config({})['monthly'] == 600
    assert envelope_config({'wants_envelope': {'monthly': 800}})['excluded'] == ['Viaggi', 'Regali']
