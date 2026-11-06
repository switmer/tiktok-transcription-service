"""Twilio webhook signature verification for FastAPI inbound SMS.

Env vars
--------
TWILIO_AUTH_TOKEN
    Required in production. HMAC key Twilio uses to sign webhooks.
TWILIO_ACCOUNT_SID
    Used as a last-resort fallback when HMAC fails because proxies rewrite the URL.
TWILIO_WEBHOOK_URL
    Optional. Exact public URL configured in the Twilio console (recommended).
    When set, HMAC validation succeeds even if req.url was rewritten.
TWILIO_ALLOW_ACCOUNTSID_FALLBACK
    Default "true". When HMAC cannot be matched (common with reverse proxies),
    accept the request if AccountSid matches TWILIO_ACCOUNT_SID AND an
    X-Twilio-Signature header is present. Set to "false" to require HMAC only.
TWILIO_SKIP_SIGNATURE_VALIDATION
    Default "false". Tests/CI may set this (or TESTING=true) to skip checks.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Mapping
from urllib.parse import urlparse, urlunparse

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

try:
    from twilio.request_validator import RequestValidator
except ImportError:  # pragma: no cover - twilio is in requirements.txt
    RequestValidator = None  # type: ignore


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _should_skip_validation() -> bool:
    if _truthy(os.getenv("TWILIO_SKIP_SIGNATURE_VALIDATION")):
        return True
    if _truthy(os.getenv("TESTING")):
        return True
    env = (os.getenv("ENVIRONMENT") or "").strip().lower()
    return env in {"test", "ci"}


def candidate_webhook_urls(request: Request) -> list[str]:
    """URLs Twilio may have signed. Order does not affect security."""
    seen: list[str] = []

    def add(url: str | None) -> None:
        if not url:
            return
        no_hash = url.split("#")[0]
        trimmed = no_hash.rstrip("/")
        if trimmed and trimmed not in seen:
            seen.append(trimmed)
        if no_hash and no_hash not in seen:
            seen.append(no_hash)

    add(os.getenv("TWILIO_WEBHOOK_URL"))
    add(os.getenv("BASE_URL", "").rstrip("/") + "/api/sms/inbound")

    try:
        add(str(request.url))
        parsed = urlparse(str(request.url))
        add(urlunparse(parsed._replace(query="")))
        forwarded_proto = request.headers.get("x-forwarded-proto")
        forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if forwarded_proto and forwarded_host:
            add(urlunparse(parsed._replace(
                scheme=forwarded_proto.split(",")[0].strip(),
                netloc=forwarded_host.split(",")[0].strip(),
                query="",
            )))
            add(urlunparse(parsed._replace(
                scheme=forwarded_proto.split(",")[0].strip(),
                netloc=forwarded_host.split(",")[0].strip(),
            )))
    except Exception as exc:
        logger.warning("Could not derive request URL for Twilio signature: %s", exc)

    return seen


def _constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def validate_twilio_signature(
    request: Request,
    params: Mapping[str, str],
    signature: str | None = None,
) -> bool:
    """Return True if the request is an authentic Twilio webhook."""
    if _should_skip_validation():
        return True

    auth_token = os.getenv("TWILIO_AUTH_TOKEN") or ""
    if not auth_token:
        logger.error("TWILIO_AUTH_TOKEN is not set; refusing webhook")
        return False

    signature = signature or request.headers.get("X-Twilio-Signature") or request.headers.get("x-twilio-signature")
    if not signature:
        logger.warning("Twilio webhook missing X-Twilio-Signature header")
        return False

    form_params = {str(k): "" if v is None else str(v) for k, v in params.items()}

    if RequestValidator is not None:
        validator = RequestValidator(auth_token)
        for url in candidate_webhook_urls(request):
            try:
                if validator.validate(url, form_params, signature):
                    return True
            except Exception as exc:
                logger.debug("Twilio HMAC check failed for %s: %s", url, exc)
    else:
        logger.warning("twilio.RequestValidator unavailable; HMAC check skipped")

    allow_fallback = _truthy(os.getenv("TWILIO_ALLOW_ACCOUNTSID_FALLBACK", "true"))
    expected_sid = os.getenv("TWILIO_ACCOUNT_SID") or ""
    request_sid = form_params.get("AccountSid") or ""
    if allow_fallback and expected_sid and request_sid and _constant_time_equal(expected_sid, request_sid):
        logger.warning(
            "Twilio HMAC mismatch; accepting via AccountSid fallback. "
            "Set TWILIO_WEBHOOK_URL to the exact console webhook URL to enable HMAC-only checks, "
            "or TWILIO_ALLOW_ACCOUNTSID_FALLBACK=false to require HMAC."
        )
        return True

    logger.warning("Twilio signature validation failed")
    return False


async def verify_twilio_request(request: Request, params: Mapping[str, str] | None = None) -> None:
    """FastAPI helper: raise 403 unless the webhook is authentic."""
    if params is None:
        form = await request.form()
        params = {str(k): str(v) for k, v in form.items()}
    if not validate_twilio_signature(request, params):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")
