import pytest
from src.utils import clean_currency, extract_tags, normalize_tags


class TestCleanCurrency:
    def test_float_passthrough(self):
        assert clean_currency(3.14) == 3.14

    def test_int_to_float(self):
        assert clean_currency(42) == 42.0

    def test_string_dot(self):
        assert clean_currency("49.90") == 49.90

    def test_string_comma(self):
        assert clean_currency("49,90") == 49.90

    def test_negative_string(self):
        assert clean_currency("-13,95") == -13.95

    def test_invalid_string_returns_zero(self):
        assert clean_currency("abc") == 0.0

    def test_none_returns_zero(self):
        assert clean_currency(None) == 0.0

    def test_empty_string_returns_zero(self):
        assert clean_currency("") == 0.0

    def test_zero(self):
        assert clean_currency(0) == 0.0

    def test_large_number_italian_format_returns_zero(self):
        # "1.234,56" -> "1.234.56" -> invalid float -> 0.0
        # clean_currency does a simple comma→dot replace, not full locale parsing
        assert clean_currency("1.234,56") == 0.0


class TestExtractTags:
    def test_single_tag(self):
        assert extract_tags("pagamento #amazon") == ["amazon"]

    def test_multiple_tags(self):
        result = extract_tags("spesa #coop #alimentari")
        assert result == ["coop", "alimentari"]

    def test_no_tags(self):
        assert extract_tags("nessun tag qui") == []

    def test_empty_string(self):
        assert extract_tags("") == []

    def test_non_string_returns_empty(self):
        assert extract_tags(None) == []
        assert extract_tags(123) == []

    def test_tag_with_numbers(self):
        assert extract_tags("#tag1 e #tag2") == ["tag1", "tag2"]

    def test_tag_at_start(self):
        assert extract_tags("#netflix mensile") == ["netflix"]


class TestNormalizeTags:
    def test_empty_list(self):
        assert normalize_tags([]) == []

    def test_none_returns_empty(self):
        assert normalize_tags(None) == []

    def test_strips_hash(self):
        assert normalize_tags(["#amazon"]) == ["amazon"]

    def test_lowercases(self):
        assert normalize_tags(["AMAZON", "Netflix"]) == ["amazon", "netflix"]

    def test_deduplicates(self):
        assert normalize_tags(["amazon", "amazon"]) == ["amazon"]

    def test_returns_sorted(self):
        result = normalize_tags(["zara", "amazon", "netflix"])
        assert result == sorted(result)

    def test_comma_separated_string_in_list(self):
        result = normalize_tags(["#amazon, #netflix"])
        assert "amazon" in result
        assert "netflix" in result

    def test_mixed_hash_and_plain(self):
        result = normalize_tags(["#amazon", "netflix"])
        assert "amazon" in result
        assert "netflix" in result
