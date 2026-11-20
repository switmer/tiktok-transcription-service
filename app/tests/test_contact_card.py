"""Offline tests for first-time ScribeTok vCard onboarding.

No production DB, no paid AI, no real Twilio/SMS.
"""
from __future__ import annotations

import base64
import os
import sys
from unittest.mock import AsyncMock

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from app.contact_card import (
    COMPLIANCE_KEYWORDS,
    HELP_KEYWORDS,
    OPT_OUT_KEYWORDS,
    VCARD_FILENAME,
    build_vcard,
    contact_card_enabled,
    escape_vcard_text,
    fold_vcard_line,
    is_compliance_keyword,
    load_photo_jpeg_bytes,
    normalize_business_tel,
    photo_http_headers,
    send_welcome_contact_card,
    vcard_http_headers,
    vcard_public_url,
    welcome_sms_body,
)
from app.models.schemas import WelcomeContactRequest


class _RpcResult:
    def __init__(self, data):
        self.data = data


class _FakeSupabase:
    def __init__(self, claim_results=None):
        self.calls = []
        self._claim_results = list(claim_results or [True])

    def rpc(self, name, params):
        self.calls.append((name, params))
        if name == "claim_sms_contact_card":
            value = self._claim_results.pop(0) if self._claim_results else False
            return _Immediate(value)
        return _Immediate(None)


class _Immediate:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return _RpcResult(self.data)


def test_compliance_keywords_cover_twilio_reserved():
    for word in ("STOP", "stop", "UNSUBSCRIBE", "HELP", "info", "START", "YES"):
        assert is_compliance_keyword(word)
    assert not is_compliance_keyword("STOP PLEASE")
    assert not is_compliance_keyword("/help")
    assert not is_compliance_keyword("https://tiktok.com/@x/video/1")
    assert "stop" in OPT_OUT_KEYWORDS
    assert "help" in HELP_KEYWORDS
    assert COMPLIANCE_KEYWORDS >= OPT_OUT_KEYWORDS


def test_escape_vcard_text():
    assert escape_vcard_text("ScribeTok") == "ScribeTok"
    assert escape_vcard_text("A;B,C\\D\nE") == "A\\;B\\,C\\\\D\\nE"


def test_fold_vcard_line_rfc6350():
    long_line = "NOTE:" + ("x" * 90)
    folded = fold_vcard_line(long_line)
    parts = folded.split("\r\n")
    assert parts[0].startswith("NOTE:")
    assert all(len(p.encode("utf-8")) <= 75 for p in parts)
    assert parts[1].startswith(" ")


def test_normalize_business_tel_from_configured_sender(monkeypatch):
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+17744727423")
    assert normalize_business_tel(None) == "+17744727423"
    assert normalize_business_tel("7744727423") == "+17744727423"
    assert normalize_business_tel("17744727423") == "+17744727423"
    # Garbage falls back to the known business number, never a personal contact.
    assert normalize_business_tel("not-a-phone") == "+17744727423"


def test_build_vcard_rfc_fields_and_photo(monkeypatch):
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+17744727423")
    monkeypatch.setenv("FRONTEND_URL", "https://scribetok.com")
    card = build_vcard()
    assert card.startswith("BEGIN:VCARD\r\n")
    assert card.endswith("END:VCARD\r\n")
    assert "VERSION:3.0" in card
    assert "FN:ScribeTok" in card
    assert "TEL;TYPE=CELL,VOICE,PREF:+17744727423" in card
    assert "URL:https://scribetok.com" in card
    assert "PHOTO;ENCODING=b;TYPE=JPEG:" in card
    jpeg = load_photo_jpeg_bytes()
    assert jpeg and jpeg[:2] == b"\xff\xd8"
    # PHOTO payload round-trips to the JPEG.
    photo_blob = ""
    collecting = False
    for raw in card.split("\r\n"):
        if raw.startswith("PHOTO;"):
            collecting = True
            photo_blob += raw.split(":", 1)[1]
            continue
        if collecting:
            if raw.startswith(" "):
                photo_blob += raw[1:]
            else:
                break
    decoded = base64.b64decode(photo_blob)
    assert decoded[:2] == b"\xff\xd8"
    assert "+16103244250" not in card  # never Steve's personal number
    assert "Bearer" not in card
    assert "user_phone" not in card


def test_build_vcard_without_photo():
    card = build_vcard(include_photo=False, photo_jpeg=None)
    assert "PHOTO;ENCODING" not in card
    assert "FN:ScribeTok" in card


def test_welcome_body_is_honest_about_delivery():
    body = welcome_sms_body("https://api.scribetok.com/api/public/contact/ScribeTok.vcf")
    assert "contact card" in body.lower() or "contacts" in body.lower()
    assert "https://api.scribetok.com/api/public/contact/ScribeTok.vcf" in body
    assert "automatically" not in body.lower()


def test_vcard_http_headers_match_twilio_guidance():
    headers = vcard_http_headers()
    assert headers["Content-Type"].startswith("text/x-vcard")
    assert VCARD_FILENAME in headers["Content-Disposition"]
    assert "inline" in headers["Content-Disposition"]
    assert headers["Cache-Control"] == "no-cache"
    photo = photo_http_headers()
    assert photo["Content-Type"] == "image/jpeg"


def test_contact_card_enabled_flag(monkeypatch):
    monkeypatch.setenv("CONTACT_CARD_ENABLED", "false")
    assert contact_card_enabled() is False
    monkeypatch.setenv("CONTACT_CARD_ENABLED", "true")
    assert contact_card_enabled() is True


@pytest.mark.asyncio
async def test_send_skips_when_claim_loses_race(monkeypatch):
    monkeypatch.setenv("CONTACT_CARD_ENABLED", "true")
    fake = _FakeSupabase(claim_results=[False])
    send_fn = AsyncMock(return_value=True)
    status, detail = await send_welcome_contact_card(
        "+15551234567", supabase_client=fake, send_fn=send_fn
    )
    assert status == "skipped"
    send_fn.assert_not_called()


@pytest.mark.asyncio
async def test_send_new_user_success(monkeypatch):
    monkeypatch.setenv("CONTACT_CARD_ENABLED", "true")
    monkeypatch.setenv("BASE_URL", "https://api.scribetok.com")
    fake = _FakeSupabase(claim_results=[True])
    send_fn = AsyncMock(return_value=True)
    status, detail = await send_welcome_contact_card(
        "+15551234567", supabase_client=fake, send_fn=send_fn
    )
    assert status == "sent"
    send_fn.assert_awaited_once()
    args, kwargs = send_fn.await_args
    assert args[0] == "+15551234567"
    assert "ScribeTok.vcf" in kwargs["media_url"]
    assert fake.calls[0][0] == "claim_sms_contact_card"
    assert any(name == "complete_sms_contact_card" for name, _ in fake.calls)
    complete = [p for name, p in fake.calls if name == "complete_sms_contact_card"][0]
    assert complete["p_success"] is True


@pytest.mark.asyncio
async def test_send_failure_is_nonfatal_and_marked_failed(monkeypatch):
    monkeypatch.setenv("CONTACT_CARD_ENABLED", "true")
    fake = _FakeSupabase(claim_results=[True])

    async def boom(*_args, **_kwargs):
        raise RuntimeError("twilio down")

    status, detail = await send_welcome_contact_card(
        "+15551234567", supabase_client=fake, send_fn=boom
    )
    assert status == "failed"
    complete = [p for name, p in fake.calls if name == "complete_sms_contact_card"][0]
    assert complete["p_success"] is False


@pytest.mark.asyncio
async def test_concurrent_claims_only_one_sends(monkeypatch):
    monkeypatch.setenv("CONTACT_CARD_ENABLED", "true")
    fake = _FakeSupabase(claim_results=[True, False])
    send_fn = AsyncMock(return_value=True)
    first = await send_welcome_contact_card("+15551234567", fake, send_fn)
    second = await send_welcome_contact_card("+15551234567", fake, send_fn)
    assert first[0] == "sent"
    assert second[0] == "skipped"
    assert send_fn.await_count == 1


@pytest.mark.asyncio
async def test_disabled_flag_skips_without_claim(monkeypatch):
    monkeypatch.setenv("CONTACT_CARD_ENABLED", "off")
    fake = _FakeSupabase(claim_results=[True])
    send_fn = AsyncMock(return_value=True)
    status, _ = await send_welcome_contact_card("+15551234567", fake, send_fn)
    assert status == "disabled"
    send_fn.assert_not_called()
    assert fake.calls == []


@pytest.mark.asyncio
async def test_public_vcard_and_icon_endpoints(monkeypatch):
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+17744727423")
    monkeypatch.setenv("FRONTEND_URL", "https://scribetok.com")
    monkeypatch.setenv("API_KEYS", "test-welcome-key")
    monkeypatch.setenv("TESTING", "true")

    from app import app as fastapi_app
    import httpx

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        vcf = await client.get("/api/public/contact/ScribeTok.vcf")
        assert vcf.status_code == 200
        assert "text/x-vcard" in vcf.headers["content-type"]
        assert "ScribeTok.vcf" in vcf.headers.get("content-disposition", "")
        assert vcf.headers.get("cache-control") == "no-cache"
        text = vcf.text
        assert "FN:ScribeTok" in text
        assert "+15555550100" not in text
        assert "sk-" not in text
        assert "eyJ" not in text  # no JWTs

        head = await client.head("/api/public/contact/ScribeTok.vcf")
        assert head.status_code == 200
        assert "text/x-vcard" in head.headers["content-type"]

        icon = await client.get("/api/public/contact/scribetok-icon.jpg")
        assert icon.status_code == 200
        assert icon.headers["content-type"].startswith("image/jpeg")
        assert icon.content[:2] == b"\xff\xd8"

        unauth = await client.post(
            "/api/sms/welcome-contact",
            json={"phone": "+15551234567"},
        )
        assert unauth.status_code in (401, 500)

        auth = await client.post(
            "/api/sms/welcome-contact",
            json={"phone": "+15551234567"},
            headers={"X-API-Key": "test-welcome-key"},
        )
        assert auth.status_code != 404
        assert auth.status_code != 401


def test_welcome_request_schema():
    req = WelcomeContactRequest(phone="+15551234567")
    assert req.phone.startswith("+")


def test_vcard_public_url_uses_base(monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://api.scribetok.com")
    monkeypatch.delenv("CONTACT_CARD_MEDIA_BASE_URL", raising=False)
    assert vcard_public_url() == "https://api.scribetok.com/api/public/contact/ScribeTok.vcf"
    assert len("ScribeTok.vcf") <= 20
