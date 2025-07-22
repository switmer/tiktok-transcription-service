-- Create credit_transactions table for complete audit trail
-- This enables tracking all credit changes with full transaction history

CREATE TABLE credit_transactions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_phone text NOT NULL REFERENCES sms_users(phone_number) ON DELETE CASCADE,
    transaction_type text NOT NULL CHECK (transaction_type IN (
        'transcription', 'purchase', 'referral_bonus', 'admin_adjustment', 
        'refund', 'refund_reversal', 'bulk_transcription', 'enterprise_purchase'
    )),
    credit_change integer NOT NULL, -- Can be negative (deduction) or positive (addition)
    balance_before integer NOT NULL,
    balance_after integer NOT NULL,
    description text NOT NULL,
    metadata jsonb DEFAULT '{}', -- For storing additional transaction details
    success boolean NOT NULL DEFAULT true,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

-- Add indexes for efficient querying
CREATE INDEX idx_credit_transactions_user_phone ON credit_transactions(user_phone);
CREATE INDEX idx_credit_transactions_type ON credit_transactions(transaction_type);
CREATE INDEX idx_credit_transactions_created_at ON credit_transactions(created_at DESC);
CREATE INDEX idx_credit_transactions_user_created ON credit_transactions(user_phone, created_at DESC);

-- Add RLS (Row Level Security) for data protection
ALTER TABLE credit_transactions ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see their own transactions
CREATE POLICY "Users can view own credit transactions" ON credit_transactions
    FOR SELECT USING (user_phone = current_setting('app.current_user_phone', true));

-- Policy: Service role can manage all transactions
CREATE POLICY "Service role can manage all credit transactions" ON credit_transactions
    FOR ALL USING (current_setting('role') = 'service_role');

-- Add comment for documentation
COMMENT ON TABLE credit_transactions IS 'Complete audit trail for all credit changes with transaction history';
COMMENT ON COLUMN credit_transactions.credit_change IS 'Positive for additions, negative for deductions';
COMMENT ON COLUMN credit_transactions.balance_before IS 'User credit balance before this transaction';
COMMENT ON COLUMN credit_transactions.balance_after IS 'User credit balance after this transaction';
COMMENT ON COLUMN credit_transactions.metadata IS 'Additional transaction details (Stripe IDs, referral info, etc.)';