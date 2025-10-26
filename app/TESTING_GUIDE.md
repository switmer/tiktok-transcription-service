# 🧪 ScribeTok SMS Monetization Testing Guide

Everything has been pushed to GitHub! Here's how to test your complete SMS credit purchase system.

## 🚀 Deployment Status: Ready!

**✅ GitHub:** All code pushed to `main` branch  
**✅ Render:** Should auto-deploy from GitHub  
**✅ Stripe:** Product created, webhook ready to configure  

---

## 📋 Testing Checklist

### **1. Environment Setup (In Render Dashboard)**

Add these environment variables to your Render service:

```bash
# Stripe Configuration
STRIPE_SECRET_KEY=sk_live_your_stripe_secret_key
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret_from_stripe
STRIPE_PAYMENT_LINK=https://buy.stripe.com/your_payment_link_here

# Existing vars (keep these)
SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_KEY=your_service_key
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
```

### **2. Stripe Webhook Configuration**

1. **In Stripe Dashboard:**
   - Go to Webhooks
   - Add endpoint: `https://api.scribetok.com/api/webhook/stripe`
   - Select event: `checkout.session.completed`
   - Copy the webhook secret (starts with `whsec_`)

2. **Create Payment Link:**
   - Go to your "10 SMS Credits" product
   - Click "Create payment link"
   - Add custom field: "Phone Number" (required)
   - Copy the payment link URL

3. **Update Environment Variables:**
   - Add `STRIPE_WEBHOOK_SECRET` and `STRIPE_PAYMENT_LINK` to Render

### **3. Test the System**

#### **A. Test SMS Commands:**

Text your Twilio number:
```
/help     → Should show new /upgrade command
/upgrade  → Should show credit balance + payment link
/vault    → Should show recent transcripts
```

#### **B. Test Credit Purchase Flow:**

1. **Text `/upgrade`** to your SMS number
2. **Click the payment link** in the response
3. **Enter your phone number** in the checkout form
4. **Complete test payment** (use test card: 4242 4242 4242 4242)
5. **Check for confirmation SMS** with new credit balance

#### **C. Test Webhook Endpoint:**

Visit: `https://api.scribetok.com/docs`
- Look for `/api/webhook/stripe` endpoint
- Should be listed under "Payment & Billing" tag

---

## 🔍 Debugging Steps

### **If SMS /upgrade doesn't work:**
```bash
# Check logs in Render dashboard
# Verify STRIPE_PAYMENT_LINK is set correctly
# Test SMS endpoint: /api/sms/webhook
```

### **If webhook doesn't fire:**
```bash
# Check Stripe webhook dashboard for delivery attempts
# Verify webhook URL is correct
# Check Render logs for webhook requests
```

### **If credits aren't added:**
```bash
# Check Supabase logs
# Verify sms_users table exists
# Check credit_purchases table for transaction records
```

---

## 🧪 Manual Testing Scripts

### **Test Database Connection:**
```python
# Run this in your Render logs or locally
from database import supabase
result = supabase.table("sms_users").select("*").limit(1).execute()
print(f"Database connection: {'✅' if result.data else '❌'}")
```

### **Test Stripe Webhook Locally:**
```bash
# Use the included test script
python app/test_stripe_integration.py
```

---

## 📱 Complete User Flow Test

**The Golden Path:**
1. **User texts any TikTok/YouTube link** → Gets transcript
2. **User texts `/upgrade`** → Gets payment link + current balance  
3. **User buys credits via Stripe** → Gets confirmation SMS
4. **User texts more links** → Uses purchased credits

---

## 🎯 Success Metrics

**✅ SMS Commands Working:** All commands respond correctly  
**✅ Payment Link Generated:** /upgrade shows Stripe link  
**✅ Webhook Receiving Events:** Stripe dashboard shows successful deliveries  
**✅ Credits Added:** User balance updates after purchase  
**✅ Confirmation SMS:** User gets "🎉 Purchase confirmed!" message  

---

## 🚨 Common Issues & Fixes

| Issue | Solution |
|-------|----------|
| SMS not working | Check Twilio credentials in Render |
| Webhook 404 error | Verify endpoint URL and deployment |
| Credits not added | Check phone number format (+1234567890) |
| Payment link 404 | Verify STRIPE_PAYMENT_LINK in environment |

---

**🎉 Once all tests pass, your SMS monetization system is live!**

Users can buy credits seamlessly via SMS and start transcribing immediately.