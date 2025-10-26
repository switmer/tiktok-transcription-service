-- Add credits and referral system to SMS users

-- Add credits fields to sms_users table
ALTER TABLE sms_users 
ADD COLUMN IF NOT EXISTS credits_remaining INTEGER DEFAULT 5,
ADD COLUMN IF NOT EXISTS free_credits_used INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS total_credits_purchased INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS referral_code TEXT UNIQUE,
ADD COLUMN IF NOT EXISTS referred_by TEXT,
ADD COLUMN IF NOT EXISTS referrals_count INTEGER DEFAULT 0;

-- Create referrals tracking table
CREATE TABLE IF NOT EXISTS referrals (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    referrer_phone TEXT NOT NULL REFERENCES sms_users(phone_number),
    referee_phone TEXT NOT NULL REFERENCES sms_users(phone_number),
    credits_awarded INTEGER DEFAULT 5,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(referrer_phone, referee_phone)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_sms_users_referral_code ON sms_users(referral_code);
CREATE INDEX IF NOT EXISTS idx_sms_users_referred_by ON sms_users(referred_by);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer_phone ON referrals(referrer_phone);
CREATE INDEX IF NOT EXISTS idx_referrals_referee_phone ON referrals(referee_phone);

-- Function to generate unique referral codes
CREATE OR REPLACE FUNCTION generate_referral_code(phone_number TEXT)
RETURNS TEXT AS $$
DECLARE
    code TEXT;
    exists_count INTEGER;
BEGIN
    -- Create a hash-based code from phone number (more privacy-friendly)
    code := UPPER(LEFT(MD5(phone_number || 'scribetok_salt'), 6));
    
    -- Check if code already exists, if so add a random suffix
    SELECT COUNT(*) INTO exists_count FROM sms_users WHERE referral_code = code;
    
    IF exists_count > 0 THEN
        code := code || FLOOR(RANDOM() * 100)::TEXT;
    END IF;
    
    RETURN code;
END;
$$ LANGUAGE plpgsql;

-- Function to handle referral bonus
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
    SET credits_remaining = credits_remaining + 5,
        referrals_count = referrals_count + 1
    WHERE phone_number = ref_phone;
    
    UPDATE sms_users 
    SET credits_remaining = credits_remaining + 5,
        referred_by = referrer_code
    WHERE phone_number = new_user_phone;
    
    -- Log the referral
    INSERT INTO referrals (referrer_phone, referee_phone, credits_awarded)
    VALUES (ref_phone, new_user_phone, 5);
    
    RETURN QUERY SELECT TRUE, ref_phone, 5, 'Referral bonus awarded';
END;
$$ LANGUAGE plpgsql;

-- Function to use a credit (for transcript)
CREATE OR REPLACE FUNCTION use_credit(user_phone TEXT)
RETURNS TABLE (
    success BOOLEAN,
    credits_remaining INTEGER,
    is_free_credit BOOLEAN,
    message TEXT
) AS $$
DECLARE
    user_row RECORD;
    remaining INTEGER;
    was_free BOOLEAN := FALSE;
BEGIN
    -- Get user data
    SELECT * INTO user_row FROM sms_users WHERE phone_number = user_phone;
    
    IF user_row IS NULL THEN
        -- Create new user with 5 free credits
        INSERT INTO sms_users (phone_number, credits_remaining, free_credits_used, referral_code)
        VALUES (user_phone, 5, 0, generate_referral_code(user_phone))
        RETURNING credits_remaining INTO remaining;
        
        remaining := remaining - 1;
        was_free := TRUE;
        
        UPDATE sms_users 
        SET credits_remaining = remaining,
            free_credits_used = 1
        WHERE phone_number = user_phone;
        
        RETURN QUERY SELECT TRUE, remaining, was_free, 'New user created with free credits';
        RETURN;
    END IF;
    
    -- Check if user has credits
    IF user_row.credits_remaining <= 0 THEN
        RETURN QUERY SELECT FALSE, 0, FALSE, 'No credits remaining';
        RETURN;
    END IF;
    
    -- Determine if this is a free credit
    was_free := user_row.free_credits_used < 5;
    
    -- Use one credit
    remaining := user_row.credits_remaining - 1;
    
    UPDATE sms_users 
    SET credits_remaining = remaining,
        free_credits_used = CASE 
            WHEN was_free THEN user_row.free_credits_used + 1 
            ELSE user_row.free_credits_used 
        END,
        total_transcriptions = user_row.total_transcriptions + 1,
        last_active = NOW()
    WHERE phone_number = user_phone;
    
    RETURN QUERY SELECT TRUE, remaining, was_free, 'Credit used successfully';
END;
$$ LANGUAGE plpgsql;

-- Generate referral codes for existing users
UPDATE sms_users 
SET referral_code = generate_referral_code(phone_number)
WHERE referral_code IS NULL;

-- Set default credits for existing users (if they don't have any)
UPDATE sms_users 
SET credits_remaining = 5
WHERE credits_remaining IS NULL OR credits_remaining = 0;

COMMENT ON TABLE referrals IS 'Track referral relationships and bonuses';
COMMENT ON COLUMN sms_users.credits_remaining IS 'Total credits available (free + purchased)';
COMMENT ON COLUMN sms_users.free_credits_used IS 'Number of free credits used (max 5)';
COMMENT ON COLUMN sms_users.referral_code IS 'Unique code for this user to share';
COMMENT ON COLUMN sms_users.referred_by IS 'Referral code that brought this user';
COMMENT ON COLUMN sms_users.referrals_count IS 'Number of successful referrals made';

SELECT 'Credits and referral system added successfully' as result;