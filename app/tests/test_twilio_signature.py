"""Unit tests for Twilio webhook signature verification."""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.twilio_signature import (
    candidate_webhook_urls,
    validate_twilio_signature,
)


class _FakeURL:
    def __init__(self, value):
        self._value = value

    def __str__(self):
        return self._value


def _request(url="https://api.scribetok.com/api/sms/inbound", headers=None):
    req = MagicMock()
    req.url = _FakeURL(url)
    req.headers = headers or {}
    return req


def test_skip_validation_in_tests(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    req = _request(headers={})
    assert validate_twilio_signature(req, {"From": "+15551234567"}) is True


def test_missing_token_fails_closed(monkeypatch):
    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_SKIP_SIGNATURE_VALIDATION", raising=False)
    req = _request(headers={"X-Twilio-Signature": "abc"})
    assert validate_twilio_signature(req, {"From": "+1555"}) is False


def test_missing_signature_header_fails(monkeypatch):
    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.delenv("TWILIO_SKIP_SIGNATURE_VALIDATION", raising=False)
    req = _request(headers={})
    assert validate_twilio_signature(req, {"From": "+1555"}) is False


def test_accountsid_fallback_requires_matching_sid(monkeypatch):
    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACexpected")
    monkeypatch.setenv("TWILIO_ALLOW_ACCOUNTSID_FALLBACK", "true")
    monkeypatch.delenv("TWILIO_SKIP_SIGNATURE_VALIDATION", raising=False)
    req = _request(headers={"X-Twilio-Signature": "not-a-real-hmac"})
    assert validate_twilio_signature(req, {"AccountSid": "ACwrong"}) is False
    assert validate_twilio_signature(req, {"AccountSid": "ACexpected"}) is True


def test_accountsid_fallback_can_be_disabled(monkeypatch):
    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACexpected")
    monkeypatch.setenv("TWILIO_ALLOW_ACCOUNTSID_FALLBACK", "false")
    monkeypatch.delenv("TWILIO_SKIP_SIGNATURE_VALIDATION", raising=False)
    req = _request(headers={"X-Twilio-Signature": "not-a-real-hmac"})
    assert validate_twilio_signature(req, {"AccountSid": "ACexpected"}) is False


def test_valid_hmac_is_accepted(monkeypatch):
    pytest.importorskip("twilio.request_validator")
    from twilio.request_validator import RequestValidator

    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret-token")
    monkeypatch.setenv("TWILIO_ALLOW_ACCOUNTSID_FALLBACK", "false")
    monkeypatch.delenv("TWILIO_SKIP_SIGNATURE_VALIDATION", raising=False)
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)

    url = "https://api.scribetok.com/api/sms/inbound"
    params = {"From": "+15551234567", "Body": "https://example.com", "AccountSid": "ACxxx"}
    signature = RequestValidator("secret-token").compute_signature(url, params)
    req = _request(url=url, headers={"X-Twilio-Signature": signature})
    monkeypatch.setenv("TWILIO_WEBHOOK_URL", url)
    assert validate_twilio_signature(req, params) is True


def test_candidate_urls_include_forwarded_and_configured(monkeypatch):
    monkeypatch.setenv("TWILIO_WEBHOOK_URL", "https://hooks.example/sms")
    monkeypatch.setenv("BASE_URL", "https://api.scribetok.com")
    req = _request(
        url="http://localhost:8000/api/sms/inbound",
        headers={"x-forwarded-proto": "https", "x-forwarded-host": "api.scribetok.com"},
    )
    urls = candidate_webhook_urls(req)
    assert "https://hooks.example/sms" in urls
    assert any(u.startswith("https://api.scribetok.com/api/sms/inbound") for u in urls)
