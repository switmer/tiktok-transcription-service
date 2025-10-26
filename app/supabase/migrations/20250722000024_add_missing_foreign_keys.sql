-- Add missing foreign key constraints based on actual Supabase schema
-- This handles the real column names and relationships from the TypeScript schema

-- 1. VERIFY CURRENT STATE AND ORPHANED DATA
DO $$
DECLARE
    orphaned_transcriptions integer;
    orphaned_messages integer;
    orphaned_purchases integer;
    orphaned_referrals integer;
BEGIN
    RAISE NOTICE 'Checking for orphaned data in actual schema...';
    
    -- Check transcriptions.user_phone → sms_users.phone_number
    SELECT COUNT(*) INTO orphaned_transcriptions
    FROM transcriptions 
    WHERE user_phone IS NOT NULL 
    AND NOT EXISTS (
        SELECT 1 FROM sms_users 
        WHERE phone_number = transcriptions.user_phone
    );
    
    -- Check user_messages.from_phone → sms_users.phone_number
    SELECT COUNT(*) INTO orphaned_messages
    FROM user_messages 
    WHERE from_phone IS NOT NULL 
    AND NOT EXISTS (
        SELECT 1 FROM sms_users 
        WHERE phone_number = user_messages.from_phone
    );
    
    -- Check credit_purchases.phone_number → sms_users.phone_number
    SELECT COUNT(*) INTO orphaned_purchases
    FROM credit_purchases 
    WHERE phone_number IS NOT NULL 
    AND NOT EXISTS (
        SELECT 1 FROM sms_users 
        WHERE phone_number = credit_purchases.phone_number
    );
    
    -- Check pending_referrals.referral_code → sms_users.referral_code
    SELECT COUNT(*) INTO orphaned_referrals
    FROM pending_referrals 
    WHERE referral_code IS NOT NULL 
    AND NOT EXISTS (
        SELECT 1 FROM sms_users 
        WHERE referral_code = pending_referrals.referral_code
    );
    
    RAISE NOTICE 'Orphaned transcriptions.user_phone: %', orphaned_transcriptions;
    RAISE NOTICE 'Orphaned user_messages.from_phone: %', orphaned_messages;
    RAISE NOTICE 'Orphaned credit_purchases.phone_number: %', orphaned_purchases;
    RAISE NOTICE 'Orphaned pending_referrals.referral_code: %', orphaned_referrals;
    
    IF orphaned_transcriptions > 0 OR orphaned_messages > 0 OR orphaned_purchases > 0 THEN
        RAISE NOTICE 'Found orphaned data - will create missing sms_users records';
    END IF;
END $$;

-- 2. CREATE MISSING SMS_USERS FOR ORPHANED DATA
DO $$
DECLARE
    orphaned_phone text;
    created_count integer := 0;
    transcription_count integer;
BEGIN
    -- Handle orphaned transcriptions.user_phone
    FOR orphaned_phone IN 
        SELECT DISTINCT t.user_phone
        FROM transcriptions t
        WHERE t.user_phone IS NOT NULL 
        AND NOT EXISTS (
            SELECT 1 FROM sms_users s 
            WHERE s.phone_number = t.user_phone
        )
    LOOP
        SELECT COUNT(*) INTO transcription_count 
        FROM transcriptions WHERE user_phone = orphaned_phone;
        
        INSERT INTO sms_users (
            id, phone_number, phone_verified, verification_code, verification_expires,
            session_token, session_expires, last_active, created_at, auth_user_id,
            credits_remaining, free_credits_used, total_credits_purchased, referral_code,
            referred_by, referrals_count, total_referral_credits_earned, referral_streak,
            last_referral_date, display_name, tiktok_handle, tiktok_profile_url,
            tiktok_linked_at, total_videos_transcribed, most_popular_video_id, most_popular_video_views
        ) VALUES (
            gen_random_uuid(), orphaned_phone, true, NULL, NULL,
            NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL,
            0, 999, 0, UPPER(substring(replace(gen_random_uuid()::text, '-', ''), 1, 6)),
            NULL, 0, 0, 0,
            NULL, NULL, NULL, NULL,
            NULL, transcription_count, NULL, 0
        );
        
        created_count := created_count + 1;
        RAISE NOTICE 'Created sms_users for transcriptions orphan: % (% transcriptions)', orphaned_phone, transcription_count;
    END LOOP;
    
    -- Handle orphaned user_messages.from_phone  
    FOR orphaned_phone IN 
        SELECT DISTINCT m.from_phone
        FROM user_messages m
        WHERE m.from_phone IS NOT NULL 
        AND NOT EXISTS (SELECT 1 FROM sms_users s WHERE s.phone_number = m.from_phone)
        AND NOT EXISTS (SELECT 1 FROM transcriptions t WHERE t.user_phone = m.from_phone)
    LOOP
        INSERT INTO sms_users (
            id, phone_number, phone_verified, verification_code, verification_expires,
            session_token, session_expires, last_active, created_at, auth_user_id,
            credits_remaining, free_credits_used, total_credits_purchased, referral_code,
            referred_by, referrals_count, total_referral_credits_earned, referral_streak,
            last_referral_date, display_name, tiktok_handle, tiktok_profile_url,
            tiktok_linked_at, total_videos_transcribed, most_popular_video_id, most_popular_video_views
        ) VALUES (
            gen_random_uuid(), orphaned_phone, true, NULL, NULL,
            NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL,
            5, 0, 0, UPPER(substring(replace(gen_random_uuid()::text, '-', ''), 1, 6)),
            NULL, 0, 0, 0,
            NULL, NULL, NULL, NULL,
            NULL, 0, NULL, 0
        );
        
        created_count := created_count + 1;
        RAISE NOTICE 'Created sms_users for user_messages orphan: %', orphaned_phone;
    END LOOP;
    
    -- Handle orphaned credit_purchases.phone_number
    FOR orphaned_phone IN 
        SELECT DISTINCT cp.phone_number
        FROM credit_purchases cp
        WHERE cp.phone_number IS NOT NULL 
        AND NOT EXISTS (SELECT 1 FROM sms_users s WHERE s.phone_number = cp.phone_number)
        AND NOT EXISTS (SELECT 1 FROM transcriptions t WHERE t.user_phone = cp.phone_number)
        AND NOT EXISTS (SELECT 1 FROM user_messages m WHERE m.from_phone = cp.phone_number)
    LOOP
        INSERT INTO sms_users (
            id, phone_number, phone_verified, verification_code, verification_expires,
            session_token, session_expires, last_active, created_at, auth_user_id,
            credits_remaining, free_credits_used, total_credits_purchased, referral_code,
            referred_by, referrals_count, total_referral_credits_earned, referral_streak,
            last_referral_date, display_name, tiktok_handle, tiktok_profile_url,
            tiktok_linked_at, total_videos_transcribed, most_popular_video_id, most_popular_video_views
        ) VALUES (
            gen_random_uuid(), orphaned_phone, true, NULL, NULL,
            NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL,
            (SELECT COALESCE(SUM(credits_purchased), 0) FROM credit_purchases WHERE phone_number = orphaned_phone),
            0, (SELECT COALESCE(SUM(credits_purchased), 0) FROM credit_purchases WHERE phone_number = orphaned_phone),
            UPPER(substring(replace(gen_random_uuid()::text, '-', ''), 1, 6)),
            NULL, 0, 0, 0,
            NULL, NULL, NULL, NULL,
            NULL, 0, NULL, 0
        );
        
        created_count := created_count + 1;
        RAISE NOTICE 'Created sms_users for credit_purchases orphan: %', orphaned_phone;
    END LOOP;
    
    IF created_count > 0 THEN
        RAISE NOTICE 'Created % missing sms_users records total', created_count;
    ELSE
        RAISE NOTICE 'No missing sms_users records needed';
    END IF;
END $$;

-- 3. ADD MISSING FOREIGN KEY CONSTRAINTS

-- FK: transcriptions.user_phone → sms_users.phone_number
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_transcriptions_user_phone') THEN
        ALTER TABLE transcriptions 
        ADD CONSTRAINT fk_transcriptions_user_phone 
        FOREIGN KEY (user_phone) REFERENCES sms_users(phone_number) 
        ON DELETE SET NULL  
        ON UPDATE CASCADE;
        RAISE NOTICE '✓ Added FK constraint: transcriptions.user_phone → sms_users.phone_number';
    ELSE
        RAISE NOTICE '✓ FK constraint transcriptions.user_phone already exists';
    END IF;
END $$;

-- FK: user_messages.from_phone → sms_users.phone_number
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_user_messages_from_phone') THEN
        ALTER TABLE user_messages 
        ADD CONSTRAINT fk_user_messages_from_phone 
        FOREIGN KEY (from_phone) REFERENCES sms_users(phone_number) 
        ON DELETE CASCADE  
        ON UPDATE CASCADE;
        RAISE NOTICE '✓ Added FK constraint: user_messages.from_phone → sms_users.phone_number';
    ELSE
        RAISE NOTICE '✓ FK constraint user_messages.from_phone already exists';
    END IF;
END $$;

-- FK: credit_purchases.phone_number → sms_users.phone_number
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_credit_purchases_phone_number') THEN
        ALTER TABLE credit_purchases 
        ADD CONSTRAINT fk_credit_purchases_phone_number 
        FOREIGN KEY (phone_number) REFERENCES sms_users(phone_number) 
        ON DELETE CASCADE  
        ON UPDATE CASCADE;
        RAISE NOTICE '✓ Added FK constraint: credit_purchases.phone_number → sms_users.phone_number';
    ELSE
        RAISE NOTICE '✓ FK constraint credit_purchases.phone_number already exists';
    END IF;
END $$;

-- FK: pending_referrals.referral_code → sms_users.referral_code (optional - referral codes might not exist)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_pending_referrals_code') THEN
        
        -- Only add if there are no orphaned referral codes
        PERFORM 1 FROM pending_referrals 
        WHERE referral_code IS NOT NULL 
        AND NOT EXISTS (SELECT 1 FROM sms_users WHERE referral_code = pending_referrals.referral_code);
        
        IF NOT FOUND THEN
            ALTER TABLE pending_referrals 
            ADD CONSTRAINT fk_pending_referrals_code 
            FOREIGN KEY (referral_code) REFERENCES sms_users(referral_code) 
            ON DELETE CASCADE  
            ON UPDATE CASCADE;
            RAISE NOTICE '✓ Added FK constraint: pending_referrals.referral_code → sms_users.referral_code';
        ELSE
            RAISE NOTICE '⚠ Orphaned referral codes found - skipping pending_referrals FK constraint';
        END IF;
    ELSE
        RAISE NOTICE '✓ FK constraint pending_referrals.referral_code already exists';
    END IF;
END $$;

-- 4. ADD SUPPORTING INDEXES FOR NEW FOREIGN KEYS
CREATE INDEX IF NOT EXISTS idx_transcriptions_user_phone_fk ON transcriptions(user_phone);
CREATE INDEX IF NOT EXISTS idx_user_messages_from_phone_fk ON user_messages(from_phone);
CREATE INDEX IF NOT EXISTS idx_credit_purchases_phone_number_fk ON credit_purchases(phone_number);
CREATE INDEX IF NOT EXISTS idx_pending_referrals_code_fk ON pending_referrals(referral_code);

-- 5. ADD COMMENTS FOR DOCUMENTATION
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'fk_transcriptions_user_phone') THEN
        EXECUTE 'COMMENT ON CONSTRAINT fk_transcriptions_user_phone ON transcriptions IS ''Links transcriptions to SMS users''';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'fk_user_messages_from_phone') THEN
        EXECUTE 'COMMENT ON CONSTRAINT fk_user_messages_from_phone ON user_messages IS ''Links messages to SMS users''';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'fk_credit_purchases_phone_number') THEN
        EXECUTE 'COMMENT ON CONSTRAINT fk_credit_purchases_phone_number ON credit_purchases IS ''Links credit purchases to SMS users''';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'fk_pending_referrals_code') THEN
        EXECUTE 'COMMENT ON CONSTRAINT fk_pending_referrals_code ON pending_referrals IS ''Links pending referrals to valid referral codes''';
    END IF;
END $$;

-- 6. FINAL VERIFICATION
DO $$
DECLARE
    new_fk_count integer;
    total_fk_count integer;
    orphaned_transcriptions integer;
    orphaned_messages integer;
    orphaned_purchases integer;
    orphaned_referrals integer;
BEGIN
    -- Count new FK constraints we just added
    SELECT COUNT(*) INTO new_fk_count
    FROM information_schema.table_constraints 
    WHERE constraint_type = 'FOREIGN KEY'
    AND constraint_name IN (
        'fk_transcriptions_user_phone',
        'fk_user_messages_from_phone', 
        'fk_credit_purchases_phone_number',
        'fk_pending_referrals_code'
    );
    
    -- Count total FK constraints in the system
    SELECT COUNT(*) INTO total_fk_count
    FROM information_schema.table_constraints 
    WHERE constraint_type = 'FOREIGN KEY'
    AND table_schema = 'public';
    
    -- Final orphan check
    SELECT COUNT(*) INTO orphaned_transcriptions
    FROM transcriptions 
    WHERE user_phone IS NOT NULL 
    AND NOT EXISTS (SELECT 1 FROM sms_users WHERE phone_number = transcriptions.user_phone);
    
    SELECT COUNT(*) INTO orphaned_messages
    FROM user_messages 
    WHERE from_phone IS NOT NULL 
    AND NOT EXISTS (SELECT 1 FROM sms_users WHERE phone_number = user_messages.from_phone);
    
    SELECT COUNT(*) INTO orphaned_purchases
    FROM credit_purchases 
    WHERE phone_number IS NOT NULL 
    AND NOT EXISTS (SELECT 1 FROM sms_users WHERE phone_number = credit_purchases.phone_number);
    
    SELECT COUNT(*) INTO orphaned_referrals
    FROM pending_referrals 
    WHERE referral_code IS NOT NULL 
    AND NOT EXISTS (SELECT 1 FROM sms_users WHERE referral_code = pending_referrals.referral_code);
    
    RAISE NOTICE '=== FOREIGN KEY MIGRATION FINAL SUMMARY ===';
    RAISE NOTICE 'New FK constraints added: %', new_fk_count;
    RAISE NOTICE 'Total FK constraints in system: %', total_fk_count;
    RAISE NOTICE 'Remaining orphaned transcriptions: %', orphaned_transcriptions;
    RAISE NOTICE 'Remaining orphaned messages: %', orphaned_messages;
    RAISE NOTICE 'Remaining orphaned purchases: %', orphaned_purchases;
    RAISE NOTICE 'Remaining orphaned referrals: %', orphaned_referrals;
    
    IF orphaned_transcriptions = 0 AND orphaned_messages = 0 AND orphaned_purchases = 0 THEN
        RAISE NOTICE '✅ SUCCESS: All critical foreign key constraints added!';
        RAISE NOTICE 'Complete referential integrity established for SMS ecosystem.';
        
        IF orphaned_referrals > 0 THEN
            RAISE NOTICE 'Note: % orphaned referral codes remain (non-critical)', orphaned_referrals;
        END IF;
    ELSE
        RAISE NOTICE '⚠ WARNING: Some orphaned data remains - check manually';
    END IF;
    
    RAISE NOTICE 'Note: referrals and user_video_stats already had FK constraints ✓';
END $$;