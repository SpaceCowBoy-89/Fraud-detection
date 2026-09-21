"""Tests for spike drill flag parsing helpers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from flag_utils import (
    normalize_flag_catalog_key,
    parse_flags_cell,
)
from dashboard.app import (
    count_catalog_flags,
    row_matches_flag_catalog,
)


def test_parse_flags_cell_python_list_repr():
    assert parse_flags_cell("['REPEATED_WORD_PATTERN']") == ['REPEATED_WORD_PATTERN']
    assert parse_flags_cell("['DIGIT_SUFFIX', 'REPEATED_WORD_PATTERN']") == [
        'DIGIT_SUFFIX', 'REPEATED_WORD_PATTERN'
    ]


def test_parse_flags_cell_json_array():
    assert parse_flags_cell('["SCRAMBLED_PATTERN"]') == ['SCRAMBLED_PATTERN']


def test_parse_flags_cell_empty():
    assert parse_flags_cell('[]') == []
    assert parse_flags_cell(None) == []


def test_normalize_flag_catalog_key_geo_variants():
    assert normalize_flag_catalog_key(
        'geo_login_mismatch_US_CA'
    ) == 'geo_login_mismatch'
    assert normalize_flag_catalog_key('REPEATED_WORD_PATTERN') == 'REPEATED_WORD_PATTERN'


def test_count_catalog_flags_per_account():
    import pandas as pd
    series = pd.Series([
        "['REPEATED_WORD_PATTERN']",
        "['DIGIT_SUFFIX', 'REPEATED_WORD_PATTERN']",
        '[]',
    ])
    rows = count_catalog_flags(series, total=3)
    by_flag = {r['flag']: r['count'] for r in rows}
    assert by_flag['REPEATED_WORD_PATTERN'] == 2
    assert by_flag['DIGIT_SUFFIX'] == 1


def test_row_matches_flag_catalog():
    cell = "['DIGIT_SUFFIX', 'REPEATED_WORD_PATTERN']"
    assert row_matches_flag_catalog(cell, 'REPEATED_WORD_PATTERN')
    assert row_matches_flag_catalog(cell, 'repeated_word_pattern')
    assert not row_matches_flag_catalog(cell, 'SCRAMBLED_PATTERN')
