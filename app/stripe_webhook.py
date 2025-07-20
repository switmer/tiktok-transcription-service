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
from database import supabase_client
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import json

# Configure logging
logger = logging.getLogger(__name__)

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Credit package configuration
CREDIT_PACKAGES = {
    "prod_SiTcSm4J45POT4": {  # Your 10 SMS Credits product ID
        "credits": 10,
        "product_name": "10 SMS Credits",
        "price": 4.75
    }
}

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
            raise HTTPException(status_code=400, detail="Missing signature")
        
        # Verify webhook signature
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except ValueError as e:
            logger.error(f"Invalid payload: {e}")
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid signature: {e}")
            raise HTTPException(status_code=400, detail="Invalid signature")
        
        # Handle the event
        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            
            # Process the successful payment
            result = await process_successful_payment(session)
            
            logger.info(f"Successfully processed payment for session {session['id']}")
            return {"status": "success", "result": result}
        
        else:
            logger.info(f"Unhandled event type: {event['type']}")
            return {"status": "ignored", "event_type": event["type"]}
    
    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Webhook error: {str(e)}")

async def process_successful_payment(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a successful payment session and credit the user's account.
    
    Args:
        session: Stripe checkout session object
        
    Returns:
        Dictionary with processing results
    """
    try:
        # Extract key information from the session
        session_id = session["id"]
        customer_email = session.get("customer_details", {}).get("email")
        phone_number = session.get("customer_details", {}).get("phone")
        
        # Get phone number from custom fields if not in customer details
        if not phone_number:
            custom_fields = session.get("custom_fields", [])
            for field in custom_fields:
                if field.get("key") == "phone_number" or "phone" in field.get("label", "").lower():
                    phone_number = field.get("text", {}).get("value")
                    break
        
        # Get phone number from metadata if still not found
        if not phone_number:
            metadata = session.get("metadata", {})
            phone_number = metadata.get("phone_number") or metadata.get("phone")
        
        if not phone_number:
            logger.error(f"No phone number found for session {session_id}")
            return {
                "success": False,
                "error": "No phone number found in payment data",
                "session_id": session_id
            }
        
        # Clean and validate phone number
        phone_number = clean_phone_number(phone_number)
        
        # Get the purchased product information
        line_items = stripe.checkout.Session.list_line_items(session_id)
        
        if not line_items.data:
            logger.error(f"No line items found for session {session_id}")
            return {
                "success": False,
                "error": "No products found in payment",
                "session_id": session_id
            }
        
        total_credits = 0
        purchased_products = []
        
        for item in line_items.data:
            price_id = item["price"]["id"]
            product_id = item["price"]["product"]
            quantity = item["quantity"]
            
            # Check if this is a known credit package
            if product_id in CREDIT_PACKAGES:
                package_info = CREDIT_PACKAGES[product_id]
                credits_to_add = package_info["credits"] * quantity
                total_credits += credits_to_add
                
                purchased_products.append({
                    "product_id": product_id,
                    "product_name": package_info["product_name"],
                    "quantity": quantity,
                    "credits": credits_to_add
                })
                
                logger.info(f"Found credit package: {package_info['product_name']} x{quantity} = {credits_to_add} credits")
        
        if total_credits == 0:
            logger.warning(f"No credit packages found in session {session_id}")
            return {
                "success": False,
                "error": "No credit packages found in purchase",
                "session_id": session_id
            }
        
        # Credit the user's account
        credit_result = await add_credits_to_user(
            phone_number=phone_number,
            credits=total_credits,
            session_id=session_id,
            customer_email=customer_email,
            purchased_products=purchased_products
        )
        
        if credit_result["success"]:
            # Send confirmation SMS
            await send_purchase_confirmation_sms(
                phone_number=phone_number,
                credits_added=total_credits,
                total_credits=credit_result["total_credits"]
            )
        
        return credit_result
        
    except Exception as e:
        logger.error(f"Error processing payment session {session.get('id', 'unknown')}: {str(e)}")
        return {
            "success": False,
            "error": f"Processing error: {str(e)}",
            "session_id": session.get("id")
        }

async def add_credits_to_user(
    phone_number: str,
    credits: int,
    session_id: str,
    customer_email: Optional[str] = None,
    purchased_products: Optional[list] = None
) -> Dict[str, Any]:
    """
    Add credits to a user's account and log the transaction.
    
    Args:
        phone_number: User's phone number
        credits: Number of credits to add
        session_id: Stripe session ID for reference
        customer_email: Customer email (optional)
        purchased_products: List of purchased products (optional)
        
    Returns:
        Dictionary with operation results
    """
    try:
        # First, ensure the user exists in sms_users table
        user_result = supabase_client.table("sms_users").select("*").eq("phone_number", phone_number).execute()
        
        if not user_result.data:
            # Create new user record
            new_user_data = {
                "phone_number": phone_number,
                "credits_remaining": credits,
                "total_messages": 0,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            if customer_email:
                new_user_data["email"] = customer_email
            
            user_insert_result = supabase_client.table("sms_users").insert(new_user_data).execute()
            
            if user_insert_result.data:
                logger.info(f"Created new user {phone_number} with {credits} credits")
                total_credits = credits
            else:
                logger.error(f"Failed to create user {phone_number}")
                return {
                    "success": False,
                    "error": "Failed to create user account",
                    "phone_number": phone_number
                }
        else:
            # Update existing user's credits
            current_credits = user_result.data[0].get("credits_remaining", 0)
            new_total = current_credits + credits
            
            update_data = {"credits_remaining": new_total}
            if customer_email and not user_result.data[0].get("email"):
                update_data["email"] = customer_email
            
            user_update_result = supabase_client.table("sms_users").update(update_data).eq("phone_number", phone_number).execute()
            
            if user_update_result.data:
                logger.info(f"Updated user {phone_number}: {current_credits} + {credits} = {new_total} credits")
                total_credits = new_total
            else:
                logger.error(f"Failed to update credits for user {phone_number}")
                return {
                    "success": False,
                    "error": "Failed to update user credits",
                    "phone_number": phone_number
                }
        
        # Log the credit purchase transaction
        transaction_data = {
            "phone_number": phone_number,
            "session_id": session_id,
            "credits_purchased": credits,
            "purchase_timestamp": datetime.now(timezone.utc).isoformat(),
            "customer_email": customer_email,
            "products": json.dumps(purchased_products) if purchased_products else None
        }
        
        # Insert into credit_purchases table (create if needed)
        try:
            supabase_client.table("credit_purchases").insert(transaction_data).execute()
            logger.info(f"Logged credit purchase transaction for {phone_number}")
        except Exception as e:
            logger.warning(f"Failed to log transaction (non-critical): {e}")
        
        return {
            "success": True,
            "phone_number": phone_number,
            "credits_added": credits,
            "total_credits": total_credits,
            "session_id": session_id
        }
        
    except Exception as e:
        logger.error(f"Error adding credits to user {phone_number}: {str(e)}")
        return {
            "success": False,
            "error": f"Database error: {str(e)}",
            "phone_number": phone_number
        }

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
        from sms_handler import send_sms
        
        message = f"🎉 Purchase confirmed! You now have {total_credits} credits ({credits_added} added). Send any TikTok/YouTube link to transcribe!"
        
        await send_sms(phone_number, message)
        logger.info(f"Sent purchase confirmation SMS to {phone_number}")
        
    except Exception as e:
        logger.error(f"Failed to send confirmation SMS to {phone_number}: {e}")
        # Don't fail the whole process if SMS fails

def clean_phone_number(phone: str) -> str:
    """
    Clean and format phone number to E.164 format.
    
    Args:
        phone: Raw phone number string
        
    Returns:
        Cleaned phone number
    """
    # Remove all non-digit characters
    digits_only = ''.join(filter(str.isdigit, phone))
    
    # Add +1 if it's a 10-digit US number
    if len(digits_only) == 10:
        return f"+1{digits_only}"
    elif len(digits_only) == 11 and digits_only.startswith('1'):
        return f"+{digits_only}"
    elif phone.startswith('+'):
        return phone
    else:
        return f"+{digits_only}"

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