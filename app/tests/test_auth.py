"""
Tests for the Phone OTP Auth endpoints.

Tests cover:
- POST /api/auth/send-otp — phone normalization, OTP generation, SMS sending
- POST /api/auth/verify-otp — code validation, session token issuance
- GET /api/auth/credits — session token validation, credit balance
- POST /api/auth/checkout — Stripe checkout session creation
- verify_session_token dependency — token lookup, expiration
- _normalize_phone helper — various phone formats
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timezone, timedelta
import os
import sys

# Add project root to sys.path so the `app` package is importable with
# relative imports intact.
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.api.auth import (
    _normalize_phone,
    verify_session_token,
    optional_session_token,
    send_otp,
    verify_otp,
    get_credits,
    create_checkout,
)
from app.core.errors import ApiError
from app.models.schemas import (
    CheckoutRequest,
    SendOtpRequest,
    VerifyOtpRequest,
)

# Module path for patch() targets
_AUTH_MOD = "app.api.auth"


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class MockResponse:
    """Mock Supabase response."""
    def __init__(self, data):
        self.data = data


class MockChain:
    """Chainable mock for Supabase query builder."""
    def __init__(self, response_data=None):
        self._response = MockResponse(response_data)

    def select(self, *a, **kw):
        return self

    def eq(self, *a, **kw):
        return self

    def limit(self, *a, **kw):
        return self

    def upsert(self, *a, **kw):
        return self

    def execute(self):
        return self._response


# ---------------------------------------------------------------------------
# _normalize_phone
# ---------------------------------------------------------------------------

class TestNormalizePhone:
    """Tests for the phone normalization helper."""

    def test_ten_digit(self):
        assert _normalize_phone("5551234567") == "+15551234567"

    def test_eleven_digit_with_leading_1(self):
        assert _normalize_phone("15551234567") == "+15551234567"

    def test_already_e164(self):
        assert _normalize_phone("+15551234567") == "+15551234567"

    def test_strips_formatting(self):
        assert _normalize_phone("(555) 123-4567") == "+15551234567"

    def test_raw_digits_no_country(self):
        # 12 digits without + => prepend +
        assert _normalize_phone("445551234567") == "+445551234567"


# ---------------------------------------------------------------------------
# verify_session_token dependency
# ---------------------------------------------------------------------------

class TestVerifySessionToken:
    """Tests for the session token validation dependency."""

    @pytest.mark.asyncio
    async def test_missing_token_raises_401(self):
        with pytest.raises(ApiError) as exc_info:
            await verify_session_token(x_session_token=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self):
        mock_sb = Mock()
        mock_sb.table.return_value = MockChain(response_data=[])

        with patch(f"{_AUTH_MOD}.supabase", mock_sb):
            with pytest.raises(ApiError) as exc_info:
                await verify_session_token(x_session_token="bad_token")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        mock_sb = Mock()
        mock_sb.table.return_value = MockChain(response_data=[{
            "phone_number": "+15551234567",
            "credits_remaining": 5,
            "session_token": "tok",
            "session_expires": past,
        }])

        with patch(f"{_AUTH_MOD}.supabase", mock_sb):
            with pytest.raises(ApiError) as exc_info:
                await verify_session_token(x_session_token="tok")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_token_returns_user(self):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        mock_sb = Mock()
        mock_sb.table.return_value = MockChain(response_data=[{
            "phone_number": "+15551234567",
            "credits_remaining": 8,
            "session_token": "valid_tok",
            "session_expires": future,
        }])

        with patch(f"{_AUTH_MOD}.supabase", mock_sb):
            result = await verify_session_token(x_session_token="valid_tok")

        assert result["phone_number"] == "+15551234567"
        assert result["credits_remaining"] == 8

    @pytest.mark.asyncio
    async def test_supabase_unavailable_raises_503(self):
        with patch(f"{_AUTH_MOD}.supabase", None):
            with pytest.raises(ApiError) as exc_info:
                await verify_session_token(x_session_token="tok")
            assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# optional_session_token dependency
# ---------------------------------------------------------------------------

class TestOptionalSessionToken:
    """Tests for the optional session token dependency."""

    @pytest.mark.asyncio
    async def test_absent_returns_none(self):
        result = await optional_session_token(x_session_token=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_present_valid_returns_user(self):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        mock_sb = Mock()
        mock_sb.table.return_value = MockChain(response_data=[{
            "phone_number": "+15551234567",
            "credits_remaining": 3,
            "session_token": "tok",
            "session_expires": future,
        }])

        with patch(f"{_AUTH_MOD}.supabase", mock_sb):
            result = await optional_session_token(x_session_token="tok")
        assert result["phone_number"] == "+15551234567"

    @pytest.mark.asyncio
    async def test_present_invalid_raises(self):
        mock_sb = Mock()
        mock_sb.table.return_value = MockChain(response_data=[])

        with patch(f"{_AUTH_MOD}.supabase", mock_sb):
            with pytest.raises(ApiError):
                await optional_session_token(x_session_token="bad")


# ---------------------------------------------------------------------------
# POST /api/auth/send-otp
# ---------------------------------------------------------------------------

class TestSendOtp:
    """Tests for the send-otp endpoint."""

    @pytest.mark.asyncio
    async def test_invalid_phone_returns_400(self):
        mock_sb = Mock()
        with patch(f"{_AUTH_MOD}.supabase", mock_sb):
            with pytest.raises(ApiError) as exc_info:
                await send_otp(SendOtpRequest(phone="123"))
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_supabase_unavailable_returns_503(self):
        with patch(f"{_AUTH_MOD}.supabase", None):
            with pytest.raises(ApiError) as exc_info:
                await send_otp(SendOtpRequest(phone="5551234567"))
            assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_successful_otp_send(self):
        mock_sb = Mock()
        # upsert call
        mock_sb.table.return_value = MockChain(response_data=[])
        # rpc call returns plaintext code
        mock_rpc_chain = Mock()
        mock_rpc_chain.execute.return_value = MockResponse([{"success": True, "code": "123456", "error": None}])
        mock_sb.rpc.return_value = mock_rpc_chain

        with patch(f"{_AUTH_MOD}.supabase", mock_sb), \
             patch(f"{_AUTH_MOD}.sms.SMSHandler.send_sms", new_callable=AsyncMock, return_value=True) as mock_send:
            result = await send_otp(SendOtpRequest(phone="5551234567"))

        assert result == {"success": True}
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert "+15551234567" in call_args[0]
        assert "123456" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_sms_failure_returns_503(self):
        mock_sb = Mock()
        mock_sb.table.return_value = MockChain(response_data=[])
        mock_rpc_chain = Mock()
        mock_rpc_chain.execute.return_value = MockResponse([{"success": True, "code": "123456", "error": None}])
        mock_sb.rpc.return_value = mock_rpc_chain

        with patch(f"{_AUTH_MOD}.supabase", mock_sb), \
             patch(f"{_AUTH_MOD}.sms.SMSHandler.send_sms", new_callable=AsyncMock, return_value=False):
            with pytest.raises(ApiError) as exc_info:
                await send_otp(SendOtpRequest(phone="5551234567"))
            assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_rate_limit_error_returns_429(self):
        mock_sb = Mock()
        mock_sb.table.return_value = MockChain(response_data=[])
        mock_sb.rpc.side_effect = Exception("Too many OTP requests")

        with patch(f"{_AUTH_MOD}.supabase", mock_sb):
            with pytest.raises(ApiError) as exc_info:
                await send_otp(SendOtpRequest(phone="5551234567"))
            assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_otp_rpc_returns_rate_limit_row(self):
        mock_sb = Mock()
        mock_sb.table.return_value = MockChain(response_data=[])
        mock_rpc_chain = Mock()
        mock_rpc_chain.execute.return_value = MockResponse([{
            "success": False, "code": None, "error": "Too many OTP requests. Try again later."
        }])
        mock_sb.rpc.return_value = mock_rpc_chain

        with patch(f"{_AUTH_MOD}.supabase", mock_sb):
            with pytest.raises(ApiError) as exc_info:
                await send_otp(SendOtpRequest(phone="5551234567"))
            assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_otp_rpc_returns_no_data(self):
        mock_sb = Mock()
        mock_sb.table.return_value = MockChain(response_data=[])
        mock_rpc_chain = Mock()
        mock_rpc_chain.execute.return_value = MockResponse(None)
        mock_sb.rpc.return_value = mock_rpc_chain

        with patch(f"{_AUTH_MOD}.supabase", mock_sb):
            with pytest.raises(ApiError) as exc_info:
                await send_otp(SendOtpRequest(phone="5551234567"))
            assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/auth/verify-otp
# ---------------------------------------------------------------------------

class TestVerifyOtp:
    """Tests for the verify-otp endpoint."""

    @pytest.mark.asyncio
    async def test_invalid_code_format_returns_400(self):
        mock_sb = Mock()
        with patch(f"{_AUTH_MOD}.supabase", mock_sb):
            with pytest.raises(ApiError) as exc_info:
                await verify_otp(VerifyOtpRequest(phone="5551234567", code="abc"))
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_wrong_code_returns_401(self):
        mock_sb = Mock()
        mock_rpc_chain = Mock()
        mock_rpc_chain.execute.return_value = MockResponse([{
            "success": False,
            "error": "Invalid code",
        }])
        mock_sb.rpc.return_value = mock_rpc_chain

        with patch(f"{_AUTH_MOD}.supabase", mock_sb):
            with pytest.raises(ApiError) as exc_info:
                await verify_otp(VerifyOtpRequest(phone="5551234567", code="000000"))
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_successful_verify(self):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        mock_sb = Mock()

        # rpc verify_otp
        mock_rpc_chain = Mock()
        mock_rpc_chain.execute.return_value = MockResponse([{
            "success": True,
            "session_token": "session_abc123",
            "session_expires": future,
        }])
        mock_sb.rpc.return_value = mock_rpc_chain

        # credits lookup
        mock_sb.table.return_value = MockChain(response_data=[{
            "credits_remaining": 5,
        }])

        with patch(f"{_AUTH_MOD}.supabase", mock_sb):
            result = await verify_otp(VerifyOtpRequest(phone="5551234567", code="123456"))

        assert result["success"] is True
        assert result["session_token"] == "session_abc123"
        assert result["expires"] == future
        assert result["phone"] == "+15551234567"
        assert result["credits_remaining"] == 5

    @pytest.mark.asyncio
    async def test_lockout_returns_429(self):
        mock_sb = Mock()
        mock_sb.rpc.side_effect = Exception("Locked out")

        with patch(f"{_AUTH_MOD}.supabase", mock_sb):
            with pytest.raises(ApiError) as exc_info:
                await verify_otp(VerifyOtpRequest(phone="5551234567", code="123456"))
            assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_supabase_unavailable_returns_503(self):
        with patch(f"{_AUTH_MOD}.supabase", None):
            with pytest.raises(ApiError) as exc_info:
                await verify_otp(VerifyOtpRequest(phone="5551234567", code="123456"))
            assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# GET /api/auth/credits
# ---------------------------------------------------------------------------

class TestGetCredits:
    """Tests for the credits endpoint."""

    @pytest.mark.asyncio
    async def test_returns_balance(self):
        session = {"phone_number": "+15551234567", "credits_remaining": 12}
        result = await get_credits(session=session)

        assert result["phone"] == "+15551234567"
        assert result["credits_remaining"] == 12
        assert result["phone_verified"] is True


# ---------------------------------------------------------------------------
# POST /api/auth/checkout
# ---------------------------------------------------------------------------

class TestCreateCheckout:
    """Tests for the checkout endpoint."""

    @pytest.mark.asyncio
    async def test_stripe_not_configured_returns_503(self):
        session = {"phone_number": "+15551234567", "credits_remaining": 0}

        with patch.dict(os.environ, {"STRIPE_SECRET_KEY": "", "STRIPE_SMS_CREDITS_PRICE_ID": ""}, clear=False):
            with pytest.raises(ApiError) as exc_info:
                await create_checkout(payload=None, session=session)
            assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_successful_checkout(self):
        session = {"phone_number": "+15551234567", "credits_remaining": 0}

        mock_checkout_session = Mock()
        mock_checkout_session.url = "https://checkout.stripe.com/session_xyz"

        mock_stripe = MagicMock()
        mock_stripe.checkout.Session.create.return_value = mock_checkout_session

        with patch.dict(os.environ, {
            "STRIPE_SECRET_KEY": "sk_test_xxx",
            "STRIPE_SMS_CREDITS_PRICE_ID": "price_xxx",
        }, clear=False):
            with patch.dict("sys.modules", {"stripe": mock_stripe}):
                result = await create_checkout(payload=None, session=session)

        assert result["checkout_url"] == "https://checkout.stripe.com/session_xyz"

    @pytest.mark.asyncio
    async def test_checkout_with_custom_credits(self):
        session = {"phone_number": "+15551234567", "credits_remaining": 0}

        mock_checkout_session = Mock()
        mock_checkout_session.url = "https://checkout.stripe.com/session_xyz"

        mock_stripe = MagicMock()
        mock_stripe.checkout.Session.create.return_value = mock_checkout_session

        with patch.dict(os.environ, {
            "STRIPE_SECRET_KEY": "sk_test_xxx",
            "STRIPE_SMS_CREDITS_PRICE_ID": "price_xxx",
        }, clear=False):
            with patch.dict("sys.modules", {"stripe": mock_stripe}):
                result = await create_checkout(
                    payload=CheckoutRequest(credits=20), session=session
                )

        assert result["checkout_url"] == "https://checkout.stripe.com/session_xyz"
        # Verify metadata included custom credits
        create_call = mock_stripe.checkout.Session.create
        if create_call.called:
            metadata = create_call.call_args[1].get("metadata", {})
            assert metadata.get("credits") == "20"


# ---------------------------------------------------------------------------
# Pydantic request model validation
# ---------------------------------------------------------------------------

class TestRequestModels:
    """Tests for request model validation."""

    def test_send_otp_requires_phone(self):
        with pytest.raises(Exception):
            SendOtpRequest()

    def test_verify_otp_requires_phone_and_code(self):
        with pytest.raises(Exception):
            VerifyOtpRequest(phone="5551234567")
        with pytest.raises(Exception):
            VerifyOtpRequest(code="123456")

    def test_checkout_defaults_to_10(self):
        req = CheckoutRequest()
        assert req.credits == 10

    def test_checkout_rejects_zero(self):
        with pytest.raises(Exception):
            CheckoutRequest(credits=0)

    def test_checkout_accepts_custom(self):
        req = CheckoutRequest(credits=25)
        assert req.credits == 25
