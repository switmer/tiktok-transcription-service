"""Regression: signed checkout.session.completed must fulfill under stripe 17.

On main before the StripeObject .get() fix, construct_event returns a Session that
rejects session.get(...), so the webhook returns 500 after signature verification.
This test must fail on that code and pass once the handler converts the session
with .to_dict() and reads line_items.has_more.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
import stripe

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stripe_webhook

TEST_WEBHOOK_SECRET = "whsec_test_stripe_webhook_regression"
PRICE_ID = "price_1RnBh3BaZtBtpc8wC4aXxkCx"


def _checkout_completed_payload(session_id: str = "cs_test_signed_123") -> str:
    event = {
        "id": "evt_test_signed_123",
        "object": "event",
        "api_version": "2024-06-20",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "object": "checkout.session",
                "mode": "payment",
                "payment_status": "paid",
                "metadata": {"phone_number": "+15551234567"},
                "customer_details": {"email": "buyer@example.com", "phone": "+15559876543"},
            }
        },
    }
    return json.dumps(event, separators=(",", ":"))


def _signed_request(payload: str):
    signature = stripe.WebhookSignature.generate_signature_header(
        payload=payload,
        secret=TEST_WEBHOOK_SECRET,
    )

    class _Request:
        headers = {"stripe-signature": signature}

        async def body(self):
            return payload.encode("utf-8")

    return _Request()


def _list_line_items_response():
    """Real ListObject so .get('has_more') fails the same way production does."""
    return stripe.ListObject.construct_from(
        {
            "object": "list",
            "data": [
                {
                    "id": "li_test",
                    "object": "item",
                    "price": {"id": PRICE_ID, "object": "price"},
                    "quantity": 1,
                }
            ],
            "has_more": False,
            "url": "/v1/checkout/sessions/cs_test_signed_123/line_items",
        },
        "sk_test_regression",
    )


@pytest.mark.asyncio
async def test_signed_checkout_session_completed_fulfills_under_stripe_17():
    assert stripe.VERSION.startswith("17."), stripe.VERSION

    payload = _checkout_completed_payload()
    request = _signed_request(payload)

    rpc_result = Mock()
    rpc_result.data = [{"applied": True, "new_balance": 10}]
    db = Mock()
    db.rpc.return_value.execute.return_value = rpc_result
    confirm = AsyncMock()

    with patch.object(stripe_webhook, "STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        with patch.object(
            stripe_webhook.stripe.checkout.Session,
            "list_line_items",
            return_value=_list_line_items_response(),
        ) as list_items:
            with patch.object(stripe_webhook, "supabase_client", db):
                with patch.object(stripe_webhook, "send_purchase_confirmation_sms", confirm):
                    result = await stripe_webhook.handle_stripe_webhook(request)

    assert result["status"] == "success"
    assert result["result"]["success"] is True
    assert result["result"]["applied"] is True
    assert result["result"]["credits_added"] == 5
    assert result["result"]["total_credits"] == 10
    list_items.assert_called_once_with("cs_test_signed_123", limit=100)
    assert db.rpc.call_args.args[0] == "fulfill_sms_credit_purchase"
    assert db.rpc.call_args.args[1]["p_phone_number"] == "+15551234567"
    assert db.rpc.call_args.args[1]["p_session_id"] == "cs_test_signed_123"
    assert db.rpc.call_args.args[1]["p_credits"] == 5
    confirm.assert_awaited_once_with("+15551234567", 5, 10)
