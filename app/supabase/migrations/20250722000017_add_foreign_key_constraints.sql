-- Add remaining foreign key constraints for complete referential integrity
-- This addresses gaps identified in the technical architecture review

-- 1. ADD FOREIGN KEY: transcriptions.user_phone → sms_users.phone_number
-- Note: This was previously a "soft FK" - now making it a real constraint
DO $$
BEGIN
    -- First, clean up any orphaned records (optional - comment out if you want to preserve data)
    -- DELETE FROM transcriptions WHERE user_phone IS NOT NULL 
    --   AND NOT EXISTS (SELECT 1 FROM sms_users WHERE phone_number = transcriptions.user_phone);
    
    -- Add the foreign key constraint
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_transcriptions_user_phone') THEN
        ALTER TABLE transcriptions 
        ADD CONSTRAINT fk_transcriptions_user_phone 
        FOREIGN KEY (user_phone) REFERENCES sms_users(phone_number) 
        ON DELETE SET NULL  -- Preserve transcriptions if user is deleted
        ON UPDATE CASCADE;  -- Update phone numbers if they change
    END IF;
END $$;

-- 2. ADD FOREIGN KEY: credit_purchases.user_phone → sms_users.phone_number
DO $$
BEGIN
    -- Clean up orphaned purchases (uncomment if needed)
    -- DELETE FROM credit_purchases WHERE user_phone IS NOT NULL 
    --   AND NOT EXISTS (SELECT 1 FROM sms_users WHERE phone_number = credit_purchases.user_phone);
    
    -- Add the foreign key constraint
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_credit_purchases_user_phone') THEN
        ALTER TABLE credit_purchases 
        ADD CONSTRAINT fk_credit_purchases_user_phone 
        FOREIGN KEY (user_phone) REFERENCES sms_users(phone_number) 
        ON DELETE CASCADE   -- Delete purchases if user is deleted
        ON UPDATE CASCADE;  -- Update phone numbers if they change
    END IF;
END $$;

-- 3. ADD FOREIGN KEY: user_messages.from_phone → sms_users.phone_number
DO $$
BEGIN
    -- Add constraint only if user_messages table exists
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'user_messages') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                       WHERE constraint_name = 'fk_user_messages_from_phone') THEN
            ALTER TABLE user_messages 
            ADD CONSTRAINT fk_user_messages_from_phone 
            FOREIGN KEY (from_phone) REFERENCES sms_users(phone_number) 
            ON DELETE CASCADE   -- Delete messages if user is deleted
            ON UPDATE CASCADE;  -- Update phone numbers if they change
        END IF;
    END IF;
END $$;

-- 4. ADD FOREIGN KEY: transcript_jobs.from_phone → sms_users.phone_number
DO $$
BEGIN
    -- Add constraint only if transcript_jobs table exists
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                       WHERE constraint_name = 'fk_transcript_jobs_from_phone') THEN
            ALTER TABLE transcript_jobs 
            ADD CONSTRAINT fk_transcript_jobs_from_phone 
            FOREIGN KEY (from_phone) REFERENCES sms_users(phone_number) 
            ON DELETE CASCADE   -- Delete jobs if user is deleted
            ON UPDATE CASCADE;  -- Update phone numbers if they change
        END IF;
    END IF;
END $$;

-- 5. STRENGTHEN EXISTING FK: transcript_jobs.transcript_id → transcriptions.task_id
-- (This was added in previous migration but let's ensure it's properly configured)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        -- Drop and recreate with better delete behavior
        IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_transcript_jobs_transcript_id') THEN
            ALTER TABLE transcript_jobs DROP CONSTRAINT fk_transcript_jobs_transcript_id;
        END IF;
        
        ALTER TABLE transcript_jobs 
        ADD CONSTRAINT fk_transcript_jobs_transcript_id 
        FOREIGN KEY (transcript_id) REFERENCES transcriptions(task_id) 
        ON DELETE CASCADE   -- Delete job if transcription is deleted
        ON UPDATE CASCADE;  -- Update ID if it changes (unlikely but safe)
    END IF;
END $$;

-- 6. ADD FOREIGN KEY: api_keys.user_id → auth.users.id (if not already present)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_api_keys_user_id') THEN
        ALTER TABLE api_keys 
        ADD CONSTRAINT fk_api_keys_user_id 
        FOREIGN KEY (user_id) REFERENCES auth.users(id) 
        ON DELETE CASCADE   -- Delete API keys if user is deleted
        ON UPDATE CASCADE;
    END IF;
END $$;

-- 7. ADD FOREIGN KEY: transcriptions.user_id → auth.users.id (if not already present)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_transcriptions_user_id') THEN
        ALTER TABLE transcriptions 
        ADD CONSTRAINT fk_transcriptions_user_id 
        FOREIGN KEY (user_id) REFERENCES auth.users(id) 
        ON DELETE SET NULL  -- Preserve transcriptions if user is deleted
        ON UPDATE CASCADE;
    END IF;
END $$;

-- 8. ADD FOREIGN KEY: sms_users.auth_user_id → auth.users.id (if not already present)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_sms_users_auth_user_id') THEN
        ALTER TABLE sms_users 
        ADD CONSTRAINT fk_sms_users_auth_user_id 
        FOREIGN KEY (auth_user_id) REFERENCES auth.users(id) 
        ON DELETE SET NULL  -- SMS user can exist without auth user
        ON UPDATE CASCADE;
    END IF;
END $$;

-- 9. ADD ADDITIONAL CONSTRAINTS for referential integrity

-- Ensure pending_referrals.referral_code references valid codes
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'pending_referrals') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                       WHERE constraint_name = 'fk_pending_referrals_code') THEN
            ALTER TABLE pending_referrals 
            ADD CONSTRAINT fk_pending_referrals_code 
            FOREIGN KEY (referral_code) REFERENCES sms_users(referral_code) 
            ON DELETE CASCADE   -- Delete pending if referrer is deleted
            ON UPDATE CASCADE;
        END IF;
    END IF;
END $$;

-- 10. ADD INDEXES to support foreign key performance
CREATE INDEX IF NOT EXISTS idx_transcriptions_user_phone_fk ON transcriptions(user_phone);
CREATE INDEX IF NOT EXISTS idx_credit_purchases_user_phone_fk ON credit_purchases(user_phone);
CREATE INDEX IF NOT EXISTS idx_transcriptions_user_id_fk ON transcriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_sms_users_auth_user_id_fk ON sms_users(auth_user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_user_id_fk ON api_keys(user_id);

-- Create conditional indexes for tables that may not exist
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'user_messages') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_user_messages_from_phone_fk ON user_messages(from_phone)';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_transcript_jobs_from_phone_fk ON transcript_jobs(from_phone)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_transcript_jobs_transcript_id_fk ON transcript_jobs(transcript_id)';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'pending_referrals') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_pending_referrals_code_fk ON pending_referrals(referral_code)';
    END IF;
END $$;

-- 11. ADD COMMENTS for documentation
COMMENT ON CONSTRAINT fk_transcriptions_user_phone ON transcriptions IS 'Links transcriptions to SMS users, preserves transcriptions if user deleted';
COMMENT ON CONSTRAINT fk_credit_purchases_user_phone ON credit_purchases IS 'Links purchases to SMS users, cascades delete to maintain integrity';
COMMENT ON CONSTRAINT fk_transcriptions_user_id ON transcriptions IS 'Links transcriptions to auth users, preserves transcriptions if user deleted';
COMMENT ON CONSTRAINT fk_api_keys_user_id ON api_keys IS 'Links API keys to auth users, cascades delete for security';

-- Success message
DO $$
BEGIN
    RAISE NOTICE 'Foreign key constraints successfully added!';
    RAISE NOTICE 'Added referential integrity for: user_phone, user_id, auth relationships';
    RAISE NOTICE 'Added supporting indexes for FK performance';
    RAISE NOTICE 'Configured appropriate cascade/set null behaviors';
END $$;