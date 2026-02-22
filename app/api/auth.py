import asyncio
import logging
import os
import re

from fastapi import APIRouter, Depends, Header

from ..core.errors import (
    ApiError,
    AUTH_INVALID,
    AUTH_REQUIRED,
    INTERNAL_ERROR,
    SERVICE_UNAVAILABLE,
    VALIDATION_ERROR,
)
from ..database import supabase
from typing import Optional

from ..models.schemas import CheckoutRequest, SendOtpRequest, VerifyOtpRequest
from .. import sms

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Phone OTP Auth"])


def _normalize_phone(raw: str) -> str:
    """Normalize a phone number to E.164 format (+1XXXXXXXXXX)."""
    phone = re.sub(r"[^\d+]", "", raw)
    if len(phone) == 10:
        phone = f"+1{phone}"
    elif len(phone) == 11 and phone.startswith("1"):
        phone = f"+{phone}"
    elif not phone.startswith("+"):
        phone = f"+{phone}"
    return phone


async def verify_session_token(x_session_token: str = Header(None)) -> dict:
    """FastAPI dependency: validate session token and return user info."""
    if not x_session_token:
        raise ApiError(401, AUTH_REQUIRED, "Missing X-Session-Token header")

    if supabase is None:
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database not available")

    try:
        result = await asyncio.to_thread(
            lambda: supabase.table("sms_users")
            .select("phone_number, credits_remaining, session_token, session_expires")
            .eq("session_token", x_session_token)
            .limit(1)
            .execute()
        )

        if not result.data:
            raise ApiError(401, AUTH_INVALID, "Invalid session token")

        user = result.data[0]

        # Check expiration
        from datetime import datetime, timezone

        expires_raw = user.get("session_expires")
        if expires_raw:
            expires = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
            if expires < datetime.now(timezone.utc):
                raise ApiError(401, AUTH_INVALID, "Session token expired")

        return {
            "phone_number": user["phone_number"],
            "credits_remaining": user.get("credits_remaining", 0),
        }

    except ApiError:
        raise
    except Exception as e:
        logger.error(f"Error validating session token: {e}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Error validating session token")


async def optional_session_token(x_session_token: str = Header(None)) -> dict | None:
    """FastAPI dependency: optionally validate session token. Returns None if absent."""
    if not x_session_token:
        return None

    try:
        return await verify_session_token(x_session_token)
    except ApiError:
        raise


# --------------------------------------------------------------------------- #
# POST /api/auth/send-otp
# --------------------------------------------------------------------------- #
@router.post("/send-otp")
async def send_otp(payload: SendOtpRequest):
    """Send a 6-digit OTP code to the given phone number."""
    if supabase is None:
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database not available")

    phone = _normalize_phone(payload.phone)

    # Basic E.164 validation
    if not re.match(r"^\+\d{10,15}$", phone):
        raise ApiError(400, VALIDATION_ERROR, "Invalid phone number format")

    try:
        # Ensure sms_users row exists (upsert with on_conflict)
        await asyncio.to_thread(
            lambda: supabase.table("sms_users")
            .upsert(
                {"phone_number": phone, "credits_remaining": 5},
                on_conflict="phone_number",
            )
            .execute()
        )

        # Call the request_otp RPC (handles rate limiting, code generation)
        otp_result = await asyncio.to_thread(
            lambda: supabase.rpc("request_otp", {"p_phone_e164": phone}).execute()
        )

        if not otp_result.data:
            raise ApiError(500, INTERNAL_ERROR, "Failed to generate OTP")

        otp_row = otp_result.data
        # RPC returns the plaintext code so we can send it via SMS
        code = otp_row.get("code") if isinstance(otp_row, dict) else otp_row[0].get("code") if isinstance(otp_row, list) else None

        if not code:
            raise ApiError(500, INTERNAL_ERROR, "Failed to generate OTP code")

        # Send OTP via Twilio
        sent = await sms.SMSHandler.send_sms(
            phone, f"Your ScribeTok verification code is: {code}"
        )
        if not sent:
            raise ApiError(503, SERVICE_UNAVAILABLE, "Failed to send SMS")

        return {"success": True}

    except ApiError:
        raise
    except Exception as e:
        error_msg = str(e)
        # Surface rate-limit errors from the RPC
        if "Too many OTP requests" in error_msg or "Too many attempts" in error_msg or "Locked out" in error_msg:
            raise ApiError(429, VALIDATION_ERROR, error_msg)
        logger.error(f"Error in send_otp: {e}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to send OTP")


# --------------------------------------------------------------------------- #
# POST /api/auth/verify-otp
# --------------------------------------------------------------------------- #
@router.post("/verify-otp")
async def verify_otp(payload: VerifyOtpRequest):
    """Verify OTP code and return a session token."""
    if supabase is None:
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database not available")

    phone = _normalize_phone(payload.phone)
    code = payload.code.strip()

    if not re.match(r"^\d{6}$", code):
        raise ApiError(400, VALIDATION_ERROR, "Code must be 6 digits")

    try:
        result = await asyncio.to_thread(
            lambda: supabase.rpc(
                "verify_otp", {"p_phone_e164": phone, "p_code": code}
            ).execute()
        )

        if not result.data:
            raise ApiError(401, AUTH_INVALID, "Invalid or expired code")

        verify_data = result.data
        if isinstance(verify_data, list):
            verify_data = verify_data[0]

        if not verify_data.get("valid"):
            msg = verify_data.get("message", "Invalid or expired code")
            raise ApiError(401, AUTH_INVALID, msg)

        session_token = verify_data.get("session_token")
        expires = verify_data.get("session_expires")

        # Fetch current credits
        credits_result = await asyncio.to_thread(
            lambda: supabase.table("sms_users")
            .select("credits_remaining")
            .eq("phone_number", phone)
            .limit(1)
            .execute()
        )

        credits_remaining = 0
        if credits_result.data:
            credits_remaining = credits_result.data[0].get("credits_remaining", 0)

        return {
            "success": True,
            "session_token": session_token,
            "expires": expires,
            "phone": phone,
            "credits_remaining": credits_remaining,
        }

    except ApiError:
        raise
    except Exception as e:
        error_msg = str(e)
        if "Too many attempts" in error_msg or "Locked out" in error_msg:
            raise ApiError(429, VALIDATION_ERROR, error_msg)
        logger.error(f"Error in verify_otp: {e}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to verify OTP")


# --------------------------------------------------------------------------- #
# GET /api/auth/credits
# --------------------------------------------------------------------------- #
@router.get("/credits")
async def get_credits(session: dict = Depends(verify_session_token)):
    """Return the authenticated user's credit balance."""
    return {
        "phone": session["phone_number"],
        "credits_remaining": session["credits_remaining"],
        "phone_verified": True,
    }


# --------------------------------------------------------------------------- #
# POST /api/auth/checkout
# --------------------------------------------------------------------------- #
@router.post("/checkout")
async def create_checkout(
    payload: Optional[CheckoutRequest] = None,
    session: dict = Depends(verify_session_token),
):
    """Create a Stripe Checkout Session for purchasing credits."""
    try:
        import stripe
    except ImportError:
        raise ApiError(503, SERVICE_UNAVAILABLE, "Stripe not available")

    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
    stripe_price_id = os.getenv("STRIPE_SMS_CREDITS_PRICE_ID")

    if not stripe.api_key or not stripe_price_id:
        raise ApiError(503, SERVICE_UNAVAILABLE, "Stripe not configured")

    credits = payload.credits if payload else 10
    phone = session["phone_number"]
    frontend_url = os.getenv("FRONTEND_URL", "https://scribetok.com")

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": stripe_price_id, "quantity": 1}],
            mode="payment",
            success_url=f"{frontend_url}/sms-payment-success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{frontend_url}/sms-payment-canceled",
            metadata={
                "phone_number": phone,
                "credits": str(credits),
                "package_name": f"{credits} SMS Credits",
                "source": "web_checkout",
            },
        )

        return {"checkout_url": checkout_session.url}

    except Exception as e:
        logger.error(f"Stripe checkout error: {e}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to create checkout session")
