"""Resolve credit balances for web and SMS users.

Credits live on ``sms_users`` and are keyed primarily by ``phone_number``
(and secondarily by ``auth_user_id`` / optional ``email``). SMS-first users
often have no email, so email-only lookups incorrectly look like a 0 balance.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


def normalize_phone(raw: Optional[str]) -> Optional[str]:
    """Normalize a phone number to E.164-ish ``+1XXXXXXXXXX`` when possible."""
    if not raw:
        return None
    phone = re.sub(r"[^\d+]", "", str(raw))
    if not phone:
        return None
    if len(phone) == 10:
        phone = f"+1{phone}"
    elif len(phone) == 11 and phone.startswith("1"):
        phone = f"+{phone}"
    elif not phone.startswith("+"):
        phone = f"+{phone}"
    return phone


def _first_credits(rows: Any) -> Optional[int]:
    """Extract credits_remaining from a supabase-style response payload."""
    if not rows:
        return None
    if isinstance(rows, dict):
        if "credits_remaining" in rows:
            value = rows.get("credits_remaining")
            return None if value is None else int(value)
        rows = rows.get("data")
    if isinstance(rows, list):
        if not rows:
            return None
        value = rows[0].get("credits_remaining")
        return None if value is None else int(value)
    return None


def _query_credits(client: Any, column: str, value: str) -> Optional[int]:
    """Query sms_users for credits by a single identity column.

    Returns:
        int when a row is found (including legitimate 0),
        None when no row matches or the lookup cannot be performed.
    """
    if client is None or value is None or value == "":
        return None
    try:
        result = (
            client.table("sms_users")
            .select("credits_remaining")
            .eq(column, value)
            .limit(1)
            .execute()
        )
        return _first_credits(getattr(result, "data", result))
    except Exception as exc:
        # Missing optional columns (e.g. email before migration) must not
        # collapse into a fake 0-credit balance.
        logger.warning("credits lookup by %s failed: %s", column, exc)
        return None


def resolve_sms_user_credits(
    client: Any,
    *,
    session_token: Optional[str] = None,
    auth_user_id: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
) -> Optional[int]:
    """Resolve credits for an authenticated identity.

    Lookup order (first hit wins):
      1. session_token
      2. auth_user_id
      3. phone_number
      4. email (optional column; skipped safely if absent)

    Returns None when the balance cannot be determined. A real balance of 0
    is returned as 0.
    """
    if isinstance(session_token, str) and session_token.strip():
        credits = _query_credits(client, "session_token", session_token.strip())
        if credits is not None:
            return credits

    if auth_user_id:
        credits = _query_credits(client, "auth_user_id", str(auth_user_id))
        if credits is not None:
            return credits

    normalized = normalize_phone(phone)
    if normalized:
        credits = _query_credits(client, "phone_number", normalized)
        if credits is not None:
            return credits

    if isinstance(email, str) and email.strip():
        credits = _query_credits(client, "email", email.strip().lower())
        if credits is not None:
            return credits
        # Also try the raw email in case historical rows were stored mixed-case
        # and no lower() trigger exists yet.
        if email.strip() != email.strip().lower():
            credits = _query_credits(client, "email", email.strip())
            if credits is not None:
                return credits

    return None


def identity_from_auth_user(user: Any) -> dict:
    """Pull lookup keys from a Supabase auth user object."""
    if user is None:
        return {"auth_user_id": None, "phone": None, "email": None}

    phone = getattr(user, "phone", None)
    email = getattr(user, "email", None)
    user_id = getattr(user, "id", None)

    # Some clients expose phone/email only via model_dump / dict
    if (phone is None or email is None or user_id is None) and hasattr(user, "model_dump"):
        try:
            data = user.model_dump()
            phone = phone or data.get("phone")
            email = email or data.get("email")
            user_id = user_id or data.get("id")
        except Exception:
            pass
    if isinstance(user, dict):
        phone = phone or user.get("phone")
        email = email or user.get("email")
        user_id = user_id or user.get("id")

    metadata = getattr(user, "user_metadata", None) or {}
    if isinstance(user, dict):
        metadata = user.get("user_metadata") or metadata
    if isinstance(metadata, dict):
        phone = phone or metadata.get("phone") or metadata.get("phone_number")

    return {
        "auth_user_id": str(user_id) if user_id else None,
        "phone": phone,
        "email": email,
    }
