import pytest
import datetime
from unittest.mock import MagicMock, patch
from src.ocr_engine import OCREngine


@pytest.fixture
def engine():
    return OCREngine()


def make_results(lines):
    """Simulate EasyOCR output: list of (bbox, text) tuples."""
    return [(None, line) for line in lines]


def run_ocr(engine, lines):
    """Patch readtext and call extract_transaction_data."""
    mock_reader = MagicMock()
    mock_reader.readtext.return_value = make_results(lines)
    engine.reader = mock_reader
    return engine.extract_transaction_data(b"fake_image_bytes")


class TestDateParsing:
    def test_oggi_sets_today(self, engine):
        today = datetime.date.today()
        txs, _ = run_ocr(engine, ['Oggi', 'Amazon', '49,90'])
        assert len(txs) == 1
        assert txs[0]['date'] == today.isoformat()

    def test_ieri_sets_yesterday(self, engine):
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        txs, _ = run_ocr(engine, ['Ieri', 'Netflix', '13,99'])
        assert len(txs) == 1
        assert txs[0]['date'] == yesterday.isoformat()

    def test_italian_date_format(self, engine):
        txs, _ = run_ocr(engine, ['7 feb', 'Coop', '35,00'])
        assert len(txs) == 1
        parsed = datetime.date.fromisoformat(txs[0]['date'])
        assert parsed.month == 2
        assert parsed.day == 7

    def test_all_months_parsed(self, engine):
        month_map = {
            'gen': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'mag': 5, 'giu': 6,
            'lug': 7, 'ago': 8, 'set': 9, 'ott': 10, 'nov': 11, 'dic': 12
        }
        for abbr, expected_month in month_map.items():
            txs, _ = run_ocr(engine, [f'5 {abbr}', 'Spesa', '20,00'])
            assert len(txs) == 1
            parsed = datetime.date.fromisoformat(txs[0]['date'])
            assert parsed.month == expected_month, f"Failed for {abbr}"


class TestAmountParsing:
    def test_basic_amount(self, engine):
        txs, _ = run_ocr(engine, ['Oggi', 'Amazon', '49,90'])
        assert txs[0]['amount'] == pytest.approx(-49.90)

    def test_amount_with_euro_sign(self, engine):
        txs, _ = run_ocr(engine, ['Oggi', 'Netflix', '13,99 €'])
        assert txs[0]['amount'] == pytest.approx(-13.99)

    def test_amount_always_negative(self, engine):
        """All amounts from expense lists are treated as negative."""
        txs, _ = run_ocr(engine, ['Oggi', 'Acquisto', '100,00'])
        assert txs[0]['amount'] < 0

    def test_explicit_negative_amount(self, engine):
        txs, _ = run_ocr(engine, ['Oggi', 'Rimborso', '-50,00'])
        assert txs[0]['amount'] == pytest.approx(-50.00)

    def test_tilde_amount(self, engine):
        txs, _ = run_ocr(engine, ['Oggi', 'Spesa varia', '~35,97'])
        assert txs[0]['amount'] == pytest.approx(-35.97)


class TestDescriptionParsing:
    def test_description_extracted(self, engine):
        txs, _ = run_ocr(engine, ['Oggi', 'Amazon Prime', '49,90'])
        assert txs[0]['description'] == 'Amazon Prime'

    def test_time_removed_from_description(self, engine):
        txs, _ = run_ocr(engine, ['Oggi', 'Amazon 14:28', '49,90'])
        assert '14:28' not in txs[0]['description']
        assert 'Amazon' in txs[0]['description']

    def test_ocr_noise_asterisk_removed(self, engine):
        txs, _ = run_ocr(engine, ['Oggi', 'Uber*corsa', '12,50'])
        assert '*' not in txs[0]['description']

    def test_month_year_header_ignored(self, engine):
        """Lines like 'febbraio 2025' should be skipped."""
        txs, _ = run_ocr(engine, ['febbraio 2025', 'Oggi', 'Spesa', '20,00'])
        assert len(txs) == 1

    def test_ignored_terms_skipped(self, engine):
        txs, _ = run_ocr(engine, ['transazioni', 'Oggi', 'Spesa', '20,00'])
        assert len(txs) == 1


class TestTransactionPairing:
    def test_orphan_amount_skipped(self, engine):
        """Amount without preceding description is skipped."""
        txs, _ = run_ocr(engine, ['Oggi', '49,90'])
        assert len(txs) == 0

    def test_date_resets_pending_desc(self, engine):
        """New date cancels orphan description from previous block."""
        txs, _ = run_ocr(engine, ['Oggi', 'Descrizione Orfana', '7 feb', 'Coop', '20,00'])
        assert len(txs) == 1
        assert txs[0]['description'] == 'Coop'

    def test_multiple_transactions_same_day(self, engine):
        txs, _ = run_ocr(engine, ['Oggi', 'Amazon', '49,90', 'Netflix', '13,99'])
        assert len(txs) == 2

    def test_multiple_days(self, engine):
        txs, _ = run_ocr(engine, [
            'Oggi', 'Amazon', '49,90',
            'Ieri', 'Coop', '35,00',
        ])
        assert len(txs) == 2
        today = datetime.date.today().isoformat()
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        dates = {t['date'] for t in txs}
        assert today in dates
        assert yesterday in dates

    def test_daily_total_line_skipped(self, engine):
        """Amount immediately after date (no description) is treated as daily total."""
        txs, _ = run_ocr(engine, ['Oggi', '-73,69 €', 'Amazon', '49,90'])
        assert len(txs) == 1
        assert txs[0]['description'] == 'Amazon'


class TestRawTextLines:
    def test_raw_lines_returned(self, engine):
        _, lines = run_ocr(engine, ['Oggi', 'Amazon', '49,90'])
        assert 'Oggi' in lines
        assert 'Amazon' in lines
        assert '49,90' in lines

    def test_empty_input_returns_empty(self, engine):
        txs, lines = run_ocr(engine, [])
        assert txs == []
        assert lines == []


class TestLazyLoading:
    def test_reader_is_none_initially(self):
        e = OCREngine()
        assert e.reader is None

    def test_get_reader_raises_without_easyocr(self):
        e = OCREngine()
        with patch.dict('sys.modules', {'easyocr': None}):
            with pytest.raises((ImportError, Exception)):
                e._get_reader()
