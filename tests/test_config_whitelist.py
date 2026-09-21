"""Affiliate whitelist parsing and lookup."""

from config import Config, normalize_affiliate_code_list


def test_normalize_affiliate_code_list_splits_commas_and_newlines():
    assert normalize_affiliate_code_list(['mofosu, qa_test']) == ['mofosu', 'qa_test']
    assert normalize_affiliate_code_list(['alpha', 'beta, gamma\n delta']) == ['alpha', 'beta', 'gamma', 'delta']


def test_is_whitelisted_handles_comma_separated_legacy_entry(tmp_path):
    cfg_path = tmp_path / 'config.json'
    cfg_path.write_text('{"whitelisted_affiliates": ["mofosu, qa_test"]}')
    config = Config(str(cfg_path))
    assert config.is_whitelisted('mofosu') is True
    assert config.is_whitelisted('qa_test') is True
    assert config.is_whitelisted('other') is False
