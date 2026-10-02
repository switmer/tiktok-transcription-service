"""Checkout must credit the SMS user supplied by our app exactly once."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from types import ModuleType
from unittest.mock import AsyncMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import stripe
except ModuleNotFoundError:
    stripe = ModuleType("stripe")
    stripe.api_key = None
    stripe.checkout = SimpleNamespace(Session=SimpleNamespace(create=Mock(), list_line_items=Mock()))
    stripe.error = SimpleNamespace(SignatureVerificationError=Exception)
    stripe.Webhook = SimpleNamespace(construct_event=Mock())
    sys.modules["stripe"] = stripe

import payment_checkout
import stripe_webhook


def test_checkout_session_carries_sms_phone():
    session = SimpleNamespace(url="https://checkout.stripe.com/test")
    with patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_example"}):
        with patch.object(payment_checkout.stripe.checkout.Session, "create", return_value=session) as create:
            url = payment_checkout.create_sms_checkout_url("+15551234567", 5, "completion_sms")

    assert url == session.url
    assert create.call_args.kwargs["metadata"]["phone_number"] == "+15551234567"
    assert create.call_args.kwargs["line_items"][0]["price"] == (
        os.getenv("STRIPE_5_CREDITS_PRICE_ID") or "price_1RnBh3BaZtBtpc8wC4aXxkCx"
    )


def paid_session(metadata=None):
    return {
        "id": "cs_test_123",
        "mode": "payment",
        "payment_status": "paid",
        "metadata": metadata if metadata is not None else {"phone_number": "+15551234567"},
        "customer_details": {"phone": "+15559876543", "email": "buyer@example.com"},
    }


@pytest.mark.asyncio
async def test_webhook_uses_app_phone_and_price_not_checkout_input():
    items = SimpleNamespace(data=[{
        "price": {"id": "price_1RnBh3BaZtBtpc8wC4aXxkCx"}, "quantity": 1,
    }], get=lambda key: False)
    credit = AsyncMock(return_value={"success": True, "applied": True, "total_credits": 8})
    confirm = AsyncMock()
    with patch.object(stripe_webhook.stripe.checkout.Session, "list_line_items", return_value=items):
        with patch.object(stripe_webhook, "add_credits_to_user", credit):
            with patch.object(stripe_webhook, "send_purchase_confirmation_sms", confirm):
                result = await stripe_webhook.process_successful_payment(
                    paid_session({"phone_number": "+15551234567", "credits": "999"})
                )

    assert result["success"] is True
    assert credit.call_args.kwargs["phone_number"] == "+15551234567"
    assert credit.call_args.kwargs["credits"] == 5
    confirm.assert_awaited_once()


@pytest.mark.asyncio
async def test_webhook_refuses_payment_without_sms_phone():
    with patch.object(stripe_webhook.stripe.checkout.Session, "list_line_items") as list_items:
        result = await stripe_webhook.process_successful_payment(paid_session({}))
    assert result["success"] is False
    list_items.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_refuses_unknown_price():
    items = SimpleNamespace(data=[{"price": {"id": "price_unknown"}, "quantity": 1}], get=lambda key: False)
    with patch.object(stripe_webhook.stripe.checkout.Session, "list_line_items", return_value=items):
        with patch.object(stripe_webhook, "add_credits_to_user", new_callable=AsyncMock) as credit:
            result = await stripe_webhook.process_successful_payment(paid_session())
    assert result["success"] is False
    credit.assert_not_awaited()


@pytest.mark.asyncio
async def test_webhook_retry_does_not_send_second_confirmation():
    items = SimpleNamespace(data=[{
        "price": {"id": "price_1RnBh3BaZtBtpc8wC4aXxkCx"}, "quantity": 1,
    }], get=lambda key: False)
    credit = AsyncMock(return_value={"success": True, "applied": False, "total_credits": 8})
    confirm = AsyncMock()
    with patch.object(stripe_webhook.stripe.checkout.Session, "list_line_items", return_value=items):
        with patch.object(stripe_webhook, "add_credits_to_user", credit):
            with patch.object(stripe_webhook, "send_purchase_confirmation_sms", confirm):
                await stripe_webhook.process_successful_payment(paid_session())
    confirm.assert_not_awaited()


@pytest.mark.asyncio
async def test_purchase_rpc_reports_duplicate_without_second_confirmation():
    db = Mock()
    db.rpc.return_value.execute.return_value.data = [{"applied": False, "new_balance": 8}]
    with patch.object(stripe_webhook, "supabase_client", db):
        result = await stripe_webhook.add_credits_to_user("+15551234567", 5, "cs_test_123")
    assert result["success"] is True
    assert result["credits_added"] == 0
    assert db.rpc.call_args.args[0] == "fulfill_sms_credit_purchase"
