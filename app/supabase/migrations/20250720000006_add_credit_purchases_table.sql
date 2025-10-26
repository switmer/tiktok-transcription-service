-- Create credit_purchases table for tracking Stripe purchases

CREATE TABLE IF NOT EXISTS credit_purchases (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    phone_number TEXT NOT NULL,
    session_id TEXT NOT NULL UNIQUE, -- Stripe session ID
    credits_purchased INTEGER NOT NULL,
    purchase_timestamp TIMESTAMPTZ DEFAULT NOW(),
    customer_email TEXT,
    products JSONB, -- Store purchased product details
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_credit_purchases_phone_number ON credit_purchases(phone_number);
CREATE INDEX IF NOT EXISTS idx_credit_purchases_session_id ON credit_purchases(session_id);
CREATE INDEX IF NOT EXISTS idx_credit_purchases_timestamp ON credit_purchases(purchase_timestamp);

-- Add RLS policy if needed
ALTER TABLE credit_purchases ENABLE ROW LEVEL SECURITY;

-- Allow service role to access all records
CREATE POLICY "Service role can access all credit purchases" ON credit_purchases
    FOR ALL USING (auth.role() = 'service_role');

-- Allow authenticated users to see their own purchases (if email matches)
CREATE POLICY "Users can view their own purchases" ON credit_purchases
    FOR SELECT USING (
        auth.role() = 'authenticated' AND 
        customer_email = auth.jwt() ->> 'email'
    );