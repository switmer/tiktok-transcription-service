#!/usr/bin/env python3
"""
Stripe webhook handler for processing SMS credit purchases.

Handles checkout.session.completed events to automatically credit users
after successful payment for SMS transcription credits.
"""

import os
import logging
import stripe
from fastapi import Request, HTTPException
from core.errors import ApiError, VALIDATION_ERROR, INTERNAL_ERROR
from database import supabase as supabase_client
from typing import Dict, Any, Optional
import re

# Configure logging
logger = logging.getLogger(__name__)

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Credit package configuration - mapped by PRICE ID
CREDIT_PACKAGES = {
    # 5 Credits - $1.99
    "price_1RnBh3BaZtBtpc8wC4aXxkCx": {
        "credits": 5,
        "product_name": "5 SMS Credits",
        "price": 1.99
    },
    # 10 Credits - $4.75
    "price_1Rn2f6BaZtBtpc8w8r76vyTJ": {
        "credits": 10,
        "product_name": "10 SMS Credits",
        "price": 4.75
    }
}
if os.getenv("STRIPE_5_CREDITS_PRICE_ID"):
    CREDIT_PACKAGES[os.environ["STRIPE_5_CREDITS_PRICE_ID"]] = CREDIT_PACKAGES["price_1RnBh3BaZtBtpc8wC4aXxkCx"]
if os.getenv("STRIPE_SMS_CREDITS_PRICE_ID"):
    CREDIT_PACKAGES[os.environ["STRIPE_SMS_CREDITS_PRICE_ID"]] = CREDIT_PACKAGES["price_1Rn2f6BaZtBtpc8w8r76vyTJ"]

async def handle_stripe_webhook(request: Request) -> Dict[str, Any]:
    """
    Handle incoming Stripe webhook events.
    
    Processes checkout.session.completed events to credit users
    after successful credit pack purchases.
    """
    try:
        # Get the request body and signature
        payload = await request.body()
        sig_header = request.headers.get("stripe-signature")
        
        if not sig_header:
            logger.error("Missing Stripe signature header")
            raise ApiError(400, VALIDATION_ERROR, "Missing signature")
        
        # Verify webhook signature
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except ValueError as e:
            logger.error(f"Invalid payload: {e}")
            raise ApiError(400, VALIDATION_ERROR, "Invalid payload")
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid signature: {e}")
            raise ApiError(400, VALIDATION_ERROR, "Invalid signature")
        
        # Handle the event
        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            
            # Process the successful payment
            result = await process_successful_payment(session)
            
            if not result["success"]:
                raise RuntimeError(f"Payment {session['id']} was not fulfilled: {result['error']}")
            logger.info(f"Successfully processed payment for session {session['id']}")
            return {"status": "success", "result": result}
        
        else:
            logger.info(f"Unhandled event type: {event['type']}")
            return {"status": "ignored", "event_type": event["type"]}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        raise ApiError(500, INTERNAL_ERROR, "Webhook processing error")

async def process_successful_payment(session: Dict[str, Any]) -> Dict[str, Any]:
    """Credit the SMS user identified by server-set Checkout Session metadata."""
    session_id = session["id"]
    if session.get("payment_status") != "paid" or session.get("mode") != "payment":
        return {"success": False, "error": "Checkout is not a paid one-time payment", "session_id": session_id}

    metadata = session.get("metadata") or {}
    phone = metadata.get("phone_number")
    if not phone or not re.fullmatch(r"\+[1-9][0-9]{9,14}", phone):
        logger.error("Paid session %s has no valid server-set SMS phone", session_id)
        return {"success": False, "error": "Missing SMS user phone in session metadata", "session_id": session_id}

    try:
        line_items = stripe.checkout.Session.list_line_items(session_id, limit=100)
        if line_items.get("has_more"):
            return {"success": False, "error": "Too many line items to verify", "session_id": session_id}
        total_credits = 0
        purchased_products = []
        for item in line_items.data:
            price = item["price"]
            price_id = price["id"]
            package = CREDIT_PACKAGES.get(price_id)
            quantity = item["quantity"]
            if not package or not isinstance(quantity, int) or quantity < 1:
                return {"success": False, "error": f"Unknown credit price or quantity: {price_id}", "session_id": session_id}
            credits = package["credits"] * quantity
            total_credits += credits
            purchased_products.append({
                "price_id": price_id,
                "product_name": package["product_name"],
                "quantity": quantity,
                "credits": credits,
            })
        if total_credits < 1:
            return {"success": False, "error": "No credit line items", "session_id": session_id}

        result = await add_credits_to_user(
            phone_number=phone,
            credits=total_credits,
            session_id=session_id,
            customer_email=(session.get("customer_details") or {}).get("email"),
            purchased_products=purchased_products,
        )
        if result["success"] and result["applied"]:
            await send_purchase_confirmation_sms(phone, total_credits, result["total_credits"])
        return result
    except Exception as exc:
        logger.exception("Could not fulfill paid session %s", session_id)
        return {"success": False, "error": str(exc), "session_id": session_id}


async def add_credits_to_user(
    phone_number: str,
    credits: int,
    session_id: str,
    customer_email: Optional[str] = None,
    purchased_products: Optional[list] = None,
) -> Dict[str, Any]:
    """Apply one Stripe session exactly once through a database transaction."""
    try:
        result = supabase_client.rpc("fulfill_sms_credit_purchase", {
            "p_phone_number": phone_number,
            "p_session_id": session_id,
            "p_credits": credits,
            "p_customer_email": customer_email,
            "p_products": purchased_products,
        }).execute()
        row = result.data[0] if isinstance(result.data, list) and result.data else result.data
        if not isinstance(row, dict) or "applied" not in row:
            raise RuntimeError("Purchase function returned no result")
        return {
            "success": True,
            "applied": row["applied"],
            "phone_number": phone_number,
            "credits_added": credits if row["applied"] else 0,
            "total_credits": row["new_balance"],
            "session_id": session_id,
        }
    except Exception as exc:
        logger.exception("Could not credit SMS user for session %s", session_id)
        return {"success": False, "error": str(exc), "session_id": session_id}


async def send_purchase_confirmation_sms(phone_number: str, credits_added: int, total_credits: int):
    """
    Send a confirmation SMS after successful credit purchase.
    
    Args:
        phone_number: User's phone number
        credits_added: Number of credits just purchased
        total_credits: User's new total credit balance
    """
    try:
        # Import here to avoid circular imports
        from sms import send_sms
        
        message = f"🎉 Purchase confirmed! You now have {total_credits} credits ({credits_added} added). Send any TikTok/YouTube link to transcribe!"
        
        await send_sms(phone_number, message)
        logger.info(f"Sent purchase confirmation SMS to {phone_number}")
        
    except Exception as e:
        logger.error(f"Failed to send confirmation SMS to {phone_number}: {e}")
        # Don't fail the whole process if SMS fails

# Test function for webhook development
async def test_webhook_locally():
    """Test webhook processing with sample data."""
    sample_session = {
        "id": "cs_test_123",
        "customer_details": {
            "email": "test@example.com",
            "phone": "+1234567890"
        },
        "metadata": {},
        "custom_fields": []
    }
    
    # Mock line items response
    import stripe
    original_list_line_items = stripe.checkout.Session.list_line_items
    
    def mock_list_line_items(session_id):
        class MockLineItems:
            data = [{
                "price": {
                    "id": "price_test_123",
                    "product": "prod_SiTcSm4J45POT4"
                },
                "quantity": 1
            }]
        return MockLineItems()
    
    stripe.checkout.Session.list_line_items = mock_list_line_items
    
    try:
        result = await process_successful_payment(sample_session)
        print(f"Test result: {result}")
        return result
    finally:
        stripe.checkout.Session.list_line_items = original_list_line_items

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_webhook_locally())
