"""Create a one-time Stripe Checkout Session linked to an SMS phone."""

import os
import re

import stripe


def create_sms_checkout_url(phone: str, credits: int, source: str) -> str:
    if not re.fullmatch(r"\+[1-9][0-9]{9,14}", phone):
        raise ValueError("Invalid SMS phone number")

    price_ids = {
        5: os.getenv("STRIPE_5_CREDITS_PRICE_ID") or "price_1RnBh3BaZtBtpc8wC4aXxkCx",
        10: os.getenv("STRIPE_SMS_CREDITS_PRICE_ID") or "price_1Rn2f6BaZtBtpc8w8r76vyTJ",
    }
    if credits not in price_ids:
        raise ValueError("Invalid credit package")

    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
    if not stripe.api_key:
        raise RuntimeError("Stripe is not configured")

    frontend_url = os.getenv("FRONTEND_URL", "https://scribetok.com")
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": price_ids[credits], "quantity": 1}],
        mode="payment",
        success_url=f"{frontend_url}/sms-payment-success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{frontend_url}/sms-payment-canceled",
        metadata={"phone_number": phone, "credits": str(credits), "source": source},
    )
    return session.url
