"""Tests for encrypted admin2 session credentials."""

from dashboard.admin_credentials import (
    seal_admin_credentials,
    unseal_admin_credentials,
    mask_username,
    admin_login_required,
)


def test_seal_unseal_roundtrip():
    secret = 'test-secret-key'
    token = seal_admin_credentials('alice', 's3cret', secret)
    creds = unseal_admin_credentials(token, secret)
    assert creds == ('alice', 's3cret')


def test_unseal_wrong_secret():
    token = seal_admin_credentials('alice', 's3cret', 'key-a')
    assert unseal_admin_credentials(token, 'key-b') is None


def test_mask_username():
    assert mask_username('pat') == 'pat***'
    assert mask_username('ab') == '***'


def test_admin_login_required_default(monkeypatch):
    monkeypatch.delenv('ADMIN2_LOGIN_REQUIRED', raising=False)
    assert admin_login_required() is True
    monkeypatch.setenv('ADMIN2_LOGIN_REQUIRED', '0')
    assert admin_login_required() is False
