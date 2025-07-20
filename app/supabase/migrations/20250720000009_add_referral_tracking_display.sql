-- Add enhanced referral tracking for "See My Referrals" feature

-- Add display fields to referrals table
ALTER TABLE referrals 
ADD COLUMN IF NOT EXISTS referee_display_name TEXT,
ADD COLUMN IF NOT EXISTS referrer_total_earned INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active';

-- Add tracking fields to sms_users for gamification
ALTER TABLE sms_users 
ADD COLUMN IF NOT EXISTS total_referral_credits_earned INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS referral_streak INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS last_referral_date TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS display_name TEXT;

-- Function to get user's referral stats and list
CREATE OR REPLACE FUNCTION get_user_referrals(user_phone TEXT)
RETURNS TABLE (
    total_referrals INTEGER,
    total_credits_earned INTEGER,
    referral_streak INTEGER,
    recent_referrals JSONB
) AS $$
DECLARE
    user_data RECORD;
    referral_list JSONB;
BEGIN
    -- Get user stats
    SELECT 
        COALESCE(referrals_count, 0) as ref_count,
        COALESCE(total_referral_credits_earned, 0) as credits_earned,
        COALESCE(referral_streak, 0) as streak
    INTO user_data
    FROM sms_users 
    WHERE phone_number = user_phone;
    
    -- Get recent referrals (last 10) with masked phone numbers
    SELECT JSONB_AGG(
        JSONB_BUILD_OBJECT(
            'phone_masked', CONCAT(
                LEFT(r.referee_phone, 2), 
                '*******', 
                RIGHT(r.referee_phone, 2)
            ),
            'display_name', COALESCE(su.display_name, 'Friend'),
            'joined_date', TO_CHAR(r.created_at, 'MM/DD'),
            'credits_awarded', r.credits_awarded,
            'days_ago', EXTRACT(DAY FROM NOW() - r.created_at)
        )
        ORDER BY r.created_at DESC
    ) INTO referral_list
    FROM referrals r
    LEFT JOIN sms_users su ON su.phone_number = r.referee_phone
    WHERE r.referrer_phone = user_phone
    LIMIT 10;
    
    RETURN QUERY SELECT 
        COALESCE(user_data.ref_count, 0),
        COALESCE(user_data.credits_earned, 0),
        COALESCE(user_data.streak, 0),
        COALESCE(referral_list, '[]'::JSONB);
END;
$$ LANGUAGE plpgsql;

-- Function to update referral tracking when bonus is awarded
CREATE OR REPLACE FUNCTION update_referral_tracking(referrer_phone TEXT, credits_awarded INTEGER)
RETURNS VOID AS $$
BEGIN
    UPDATE sms_users 
    SET 
        total_referral_credits_earned = COALESCE(total_referral_credits_earned, 0) + credits_awarded,
        referral_streak = CASE 
            WHEN last_referral_date IS NULL OR last_referral_date < NOW() - INTERVAL '7 days' 
            THEN 1 
            ELSE COALESCE(referral_streak, 0) + 1 
        END,
        last_referral_date = NOW()
    WHERE phone_number = referrer_phone;
END;
$$ LANGUAGE plpgsql;

-- Update the existing process_referral function to include tracking
CREATE OR REPLACE FUNCTION process_referral(referrer_code TEXT, new_user_phone TEXT)
RETURNS TABLE (
    success BOOLEAN,
    referrer_phone TEXT,
    credits_awarded INTEGER,
    message TEXT
) AS $$
DECLARE
    ref_phone TEXT;
    ref_count INTEGER;
    credits_to_award INTEGER := 5;
BEGIN
    -- Find referrer by code
    SELECT phone_number INTO ref_phone 
    FROM sms_users 
    WHERE referral_code = referrer_code;
    
    IF ref_phone IS NULL THEN
        RETURN QUERY SELECT FALSE, NULL::TEXT, 0, 'Invalid referral code';
        RETURN;
    END IF;
    
    -- Check if referral already exists
    SELECT COUNT(*) INTO ref_count 
    FROM referrals 
    WHERE referrer_phone = ref_phone AND referee_phone = new_user_phone;
    
    IF ref_count > 0 THEN
        RETURN QUERY SELECT FALSE, ref_phone, 0, 'Referral already processed';
        RETURN;
    END IF;
    
    -- Award credits to both users
    UPDATE sms_users 
    SET credits_remaining = credits_remaining + credits_to_award,
        referrals_count = referrals_count + 1
    WHERE phone_number = ref_phone;
    
    UPDATE sms_users 
    SET credits_remaining = credits_remaining + credits_to_award,
        referred_by = referrer_code
    WHERE phone_number = new_user_phone;
    
    -- Log the referral with enhanced tracking
    INSERT INTO referrals (referrer_phone, referee_phone, credits_awarded)
    VALUES (ref_phone, new_user_phone, credits_to_award);
    
    -- Update referral tracking stats
    PERFORM update_referral_tracking(ref_phone, credits_to_award);
    
    RETURN QUERY SELECT TRUE, ref_phone, credits_to_award, 'Referral bonus awarded';
END;
$$ LANGUAGE plpgsql;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_referrals_created_at ON referrals(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sms_users_display_name ON sms_users(display_name);

-- Update existing referrals to set tracking data
UPDATE sms_users 
SET total_referral_credits_earned = (
    SELECT COALESCE(SUM(credits_awarded), 0) 
    FROM referrals 
    WHERE referrer_phone = sms_users.phone_number
)
WHERE EXISTS (
    SELECT 1 FROM referrals WHERE referrer_phone = sms_users.phone_number
);

COMMENT ON FUNCTION get_user_referrals IS 'Get comprehensive referral stats and recent referrals for display';
COMMENT ON COLUMN referrals.referee_display_name IS 'Optional display name for referred user';
COMMENT ON COLUMN sms_users.total_referral_credits_earned IS 'Total credits earned from successful referrals';
COMMENT ON COLUMN sms_users.referral_streak IS 'Current streak of days with referrals';

SELECT 'Referral tracking display system added successfully' as result;