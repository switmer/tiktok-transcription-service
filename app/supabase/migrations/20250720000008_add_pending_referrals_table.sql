-- Create pending_referrals table for tracking referral codes from web visits

CREATE TABLE IF NOT EXISTS pending_referrals (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    referral_code TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_by TEXT, -- Phone number that used this referral
    used_at TIMESTAMPTZ,
    ip_address TEXT,
    user_agent TEXT
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_pending_referrals_code ON pending_referrals(referral_code);
CREATE INDEX IF NOT EXISTS idx_pending_referrals_expires ON pending_referrals(expires_at);
CREATE INDEX IF NOT EXISTS idx_pending_referrals_used_by ON pending_referrals(used_by);

-- Function to find and use a pending referral
CREATE OR REPLACE FUNCTION use_pending_referral(user_phone TEXT)
RETURNS TEXT AS $$
DECLARE
    referral_code TEXT;
    ref_id UUID;
BEGIN
    -- Find the most recent unused referral for this phone number
    -- This is a simple approach - in production you might want more sophisticated matching
    SELECT pr.referral_code, pr.id INTO referral_code, ref_id
    FROM pending_referrals pr
    WHERE pr.used_by IS NULL 
        AND pr.expires_at > NOW()
    ORDER BY pr.created_at DESC
    LIMIT 1;
    
    IF referral_code IS NOT NULL THEN
        -- Mark as used
        UPDATE pending_referrals 
        SET used_by = user_phone, used_at = NOW()
        WHERE id = ref_id;
        
        RETURN referral_code;
    END IF;
    
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Function to cleanup expired referrals (run periodically)
CREATE OR REPLACE FUNCTION cleanup_expired_referrals()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM pending_referrals 
    WHERE expires_at < NOW() - INTERVAL '7 days';
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Add RLS policy if needed
ALTER TABLE pending_referrals ENABLE ROW LEVEL SECURITY;

-- Allow service role to access all records
CREATE POLICY "Service role can access all pending referrals" ON pending_referrals
    FOR ALL USING (auth.role() = 'service_role');

COMMENT ON TABLE pending_referrals IS 'Track referral codes from web visits before SMS contact';
COMMENT ON COLUMN pending_referrals.referral_code IS 'Referral code from the URL';
COMMENT ON COLUMN pending_referrals.expires_at IS 'When this referral tracking expires (24 hours)';
COMMENT ON COLUMN pending_referrals.used_by IS 'Phone number that eventually used this referral';

SELECT 'Pending referrals table created successfully' as result;