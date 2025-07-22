-- Add foreign key constraints using the actual table schemas
-- Final version based on complete schema analysis

-- 1. VERIFY NO ORPHANED DATA EXISTS
DO $$
DECLARE
    orphaned_transcriptions integer;
    orphaned_messages integer;
    orphaned_user_ids integer;
    orphaned_auth_ids integer;
BEGIN
    RAISE NOTICE 'Checking for orphaned data before adding FK constraints...';
    
    -- Check transcriptions.user_phone orphans
    SELECT COUNT(*) INTO orphaned_transcriptions
    FROM transcriptions 
    WHERE user_phone IS NOT NULL 
    AND NOT EXISTS (
        SELECT 1 FROM sms_users 
        WHERE phone_number = transcriptions.user_phone
    );
    
    -- Check user_messages.from_phone orphans  
    SELECT COUNT(*) INTO orphaned_messages
    FROM user_messages 
    WHERE from_phone IS NOT NULL 
    AND NOT EXISTS (
        SELECT 1 FROM sms_users 
        WHERE phone_number = user_messages.from_phone
    );
    
    -- Check transcriptions.user_id orphans (if auth.users exists)
    SELECT COUNT(*) INTO orphaned_user_ids
    FROM transcriptions 
    WHERE user_id IS NOT NULL 
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'auth' AND table_name = 'users')
    AND NOT EXISTS (
        SELECT 1 FROM auth.users 
        WHERE id = transcriptions.user_id
    );
    
    -- Check sms_users.auth_user_id orphans (if auth.users exists)
    SELECT COUNT(*) INTO orphaned_auth_ids
    FROM sms_users 
    WHERE auth_user_id IS NOT NULL 
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'auth' AND table_name = 'users')
    AND NOT EXISTS (
        SELECT 1 FROM auth.users 
        WHERE id = sms_users.auth_user_id
    );
    
    RAISE NOTICE 'Orphaned transcriptions.user_phone: %', orphaned_transcriptions;
    RAISE NOTICE 'Orphaned user_messages.from_phone: %', orphaned_messages;
    RAISE NOTICE 'Orphaned transcriptions.user_id: %', orphaned_user_ids;
    RAISE NOTICE 'Orphaned sms_users.auth_user_id: %', orphaned_auth_ids;
    
    IF orphaned_transcriptions > 0 OR orphaned_messages > 0 THEN
        RAISE NOTICE 'Found orphaned SMS data - will create missing sms_users records';
    END IF;
    
    IF orphaned_user_ids > 0 OR orphaned_auth_ids > 0 THEN
        RAISE NOTICE 'Found orphaned auth data - will clean up before adding FK constraints';
    END IF;
END $$;

-- 2. CREATE MISSING SMS_USERS FOR ORPHANED DATA (IF ANY)
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
        -- Count transcriptions for this phone
        SELECT COUNT(*) INTO transcription_count 
        FROM transcriptions WHERE user_phone = orphaned_phone;
        
        INSERT INTO sms_users (
            id,
            phone_number,
            phone_verified,
            verification_code,
            verification_expires,
            session_token,
            session_expires,
            last_active,
            created_at,
            auth_user_id,
            credits_remaining,
            free_credits_used,
            total_credits_purchased,
            referral_code,
            referred_by,
            referrals_count,
            total_referral_credits_earned,
            referral_streak,
            last_referral_date,
            display_name,
            tiktok_handle,
            tiktok_profile_url,
            tiktok_linked_at,
            total_videos_transcribed,
            most_popular_video_id,
            most_popular_video_views
        ) VALUES (
            gen_random_uuid(),
            orphaned_phone,
            true,  -- Assume verified since they have transcriptions
            NULL,
            NULL,
            NULL,
            NULL,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            NULL,
            0,     -- No remaining credits
            999,   -- High usage to indicate legacy user
            0,
            UPPER(substring(replace(gen_random_uuid()::text, '-', ''), 1, 6)),
            NULL,
            0,
            0,
            0,
            NULL,
            NULL,
            NULL,
            NULL,
            NULL,
            transcription_count,
            NULL,
            0
        );
        
        created_count := created_count + 1;
        RAISE NOTICE 'Created sms_users record for transcriptions orphan: % (% transcriptions)', orphaned_phone, transcription_count;
    END LOOP;
    
    -- Handle orphaned user_messages.from_phone
    FOR orphaned_phone IN 
        SELECT DISTINCT m.from_phone
        FROM user_messages m
        WHERE m.from_phone IS NOT NULL 
        AND NOT EXISTS (
            SELECT 1 FROM sms_users s 
            WHERE s.phone_number = m.from_phone
        )
        AND NOT EXISTS (
            SELECT 1 FROM transcriptions t
            WHERE t.user_phone = m.from_phone  -- Skip if already handled above
        )
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
        RAISE NOTICE 'Created sms_users record for user_messages orphan: %', orphaned_phone;
    END LOOP;
    
    IF created_count > 0 THEN
        RAISE NOTICE 'Created % missing sms_users records', created_count;
    ELSE
        RAISE NOTICE 'No missing sms_users records needed';
    END IF;
END $$;

-- 3. CLEAN UP ORPHANED AUTH REFERENCES
DO $$
DECLARE
    cleaned_user_ids integer := 0;
    cleaned_auth_ids integer := 0;
BEGIN
    -- Clean orphaned transcriptions.user_id (if auth.users exists)
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'auth' AND table_name = 'users') THEN
        UPDATE transcriptions SET user_id = NULL 
        WHERE user_id IS NOT NULL 
        AND NOT EXISTS (SELECT 1 FROM auth.users WHERE id = transcriptions.user_id);
        GET DIAGNOSTICS cleaned_user_ids = ROW_COUNT;
        
        -- Clean orphaned sms_users.auth_user_id
        UPDATE sms_users SET auth_user_id = NULL 
        WHERE auth_user_id IS NOT NULL 
        AND NOT EXISTS (SELECT 1 FROM auth.users WHERE id = sms_users.auth_user_id);
        GET DIAGNOSTICS cleaned_auth_ids = ROW_COUNT;
        
        IF cleaned_user_ids > 0 THEN
            RAISE NOTICE 'Cleaned % orphaned transcriptions.user_id references', cleaned_user_ids;
        END IF;
        
        IF cleaned_auth_ids > 0 THEN
            RAISE NOTICE 'Cleaned % orphaned sms_users.auth_user_id references', cleaned_auth_ids;
        END IF;
    ELSE
        RAISE NOTICE 'auth.users table not found - skipping auth reference cleanup';
    END IF;
END $$;

-- 4. ADD FOREIGN KEY CONSTRAINTS

-- FK: transcriptions.user_phone → sms_users.phone_number
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_transcriptions_user_phone') THEN
        ALTER TABLE transcriptions 
        ADD CONSTRAINT fk_transcriptions_user_phone 
        FOREIGN KEY (user_phone) REFERENCES sms_users(phone_number) 
        ON DELETE SET NULL  -- Preserve transcriptions if user is deleted
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
        ON DELETE CASCADE  -- Delete messages if user is deleted
        ON UPDATE CASCADE;
        RAISE NOTICE '✓ Added FK constraint: user_messages.from_phone → sms_users.phone_number';
    ELSE
        RAISE NOTICE '✓ FK constraint user_messages.from_phone already exists';
    END IF;
END $$;

-- FK: transcriptions.user_id → auth.users.id (if auth.users exists)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_transcriptions_user_id') THEN
        
        -- Only add if auth.users table exists
        IF EXISTS (SELECT 1 FROM information_schema.tables 
                   WHERE table_schema = 'auth' AND table_name = 'users') THEN
            ALTER TABLE transcriptions 
            ADD CONSTRAINT fk_transcriptions_user_id 
            FOREIGN KEY (user_id) REFERENCES auth.users(id) 
            ON DELETE SET NULL  -- Preserve transcriptions if user is deleted
            ON UPDATE CASCADE;
            RAISE NOTICE '✓ Added FK constraint: transcriptions.user_id → auth.users.id';
        ELSE
            RAISE NOTICE 'ℹ auth.users table not found - skipping user_id FK constraint';
        END IF;
    ELSE
        RAISE NOTICE '✓ FK constraint transcriptions.user_id already exists';
    END IF;
END $$;

-- FK: sms_users.auth_user_id → auth.users.id (if auth.users exists)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_sms_users_auth_user_id') THEN
        
        -- Only add if auth.users table exists
        IF EXISTS (SELECT 1 FROM information_schema.tables 
                   WHERE table_schema = 'auth' AND table_name = 'users') THEN
            ALTER TABLE sms_users 
            ADD CONSTRAINT fk_sms_users_auth_user_id 
            FOREIGN KEY (auth_user_id) REFERENCES auth.users(id) 
            ON DELETE SET NULL  -- SMS user can exist without auth user
            ON UPDATE CASCADE;
            RAISE NOTICE '✓ Added FK constraint: sms_users.auth_user_id → auth.users.id';
        ELSE
            RAISE NOTICE 'ℹ auth.users table not found - skipping auth_user_id FK constraint';
        END IF;
    ELSE
        RAISE NOTICE '✓ FK constraint sms_users.auth_user_id already exists';
    END IF;
END $$;

-- 5. ADD SUPPORTING INDEXES FOR PERFORMANCE
CREATE INDEX IF NOT EXISTS idx_transcriptions_user_phone_fk ON transcriptions(user_phone);
CREATE INDEX IF NOT EXISTS idx_user_messages_from_phone_fk ON user_messages(from_phone);
CREATE INDEX IF NOT EXISTS idx_transcriptions_user_id_fk ON transcriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_sms_users_auth_user_id_fk ON sms_users(auth_user_id);

-- 6. ADD COMMENTS FOR DOCUMENTATION
DO $$
BEGIN
    -- Add comments for constraints that were successfully created
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'fk_transcriptions_user_phone') THEN
        EXECUTE 'COMMENT ON CONSTRAINT fk_transcriptions_user_phone ON transcriptions IS ''Links transcriptions to SMS users, preserves transcriptions if user deleted''';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'fk_user_messages_from_phone') THEN
        EXECUTE 'COMMENT ON CONSTRAINT fk_user_messages_from_phone ON user_messages IS ''Links messages to SMS users, cascades delete to maintain integrity''';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'fk_transcriptions_user_id') THEN
        EXECUTE 'COMMENT ON CONSTRAINT fk_transcriptions_user_id ON transcriptions IS ''Links transcriptions to auth users, preserves transcriptions if user deleted''';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'fk_sms_users_auth_user_id') THEN
        EXECUTE 'COMMENT ON CONSTRAINT fk_sms_users_auth_user_id ON sms_users IS ''Links SMS users to auth users, allows SMS users without auth accounts''';
    END IF;
END $$;

-- 7. FINAL VERIFICATION AND SUMMARY
DO $$
DECLARE
    fk_count integer;
    total_transcriptions integer;
    total_messages integer;
    total_sms_users integer;
    orphaned_transcriptions integer;
    orphaned_messages integer;
    auth_table_exists boolean;
BEGIN
    -- Count successful FK constraints
    SELECT COUNT(*) INTO fk_count
    FROM information_schema.table_constraints 
    WHERE constraint_type = 'FOREIGN KEY'
    AND constraint_name LIKE 'fk_%'
    AND table_name IN ('transcriptions', 'user_messages', 'sms_users');
    
    -- Get table counts
    SELECT COUNT(*) INTO total_transcriptions FROM transcriptions;
    SELECT COUNT(*) INTO total_messages FROM user_messages;
    SELECT COUNT(*) INTO total_sms_users FROM sms_users;
    
    -- Check for any remaining orphaned data
    SELECT COUNT(*) INTO orphaned_transcriptions
    FROM transcriptions 
    WHERE user_phone IS NOT NULL 
    AND NOT EXISTS (SELECT 1 FROM sms_users WHERE phone_number = transcriptions.user_phone);
    
    SELECT COUNT(*) INTO orphaned_messages
    FROM user_messages 
    WHERE from_phone IS NOT NULL 
    AND NOT EXISTS (SELECT 1 FROM sms_users WHERE phone_number = user_messages.from_phone);
    
    -- Check if auth.users exists
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) INTO auth_table_exists;
    
    RAISE NOTICE '=== FOREIGN KEY MIGRATION SUMMARY ===';
    RAISE NOTICE 'Foreign key constraints added: %', fk_count;
    RAISE NOTICE 'Total transcriptions: %', total_transcriptions;
    RAISE NOTICE 'Total user messages: %', total_messages;
    RAISE NOTICE 'Total SMS users: %', total_sms_users;
    RAISE NOTICE 'Remaining orphaned transcriptions: %', orphaned_transcriptions;
    RAISE NOTICE 'Remaining orphaned messages: %', orphaned_messages;
    RAISE NOTICE 'Auth users table exists: %', auth_table_exists;
    
    IF orphaned_transcriptions = 0 AND orphaned_messages = 0 THEN
        RAISE NOTICE '✅ SUCCESS: All foreign key constraints added successfully!';
        RAISE NOTICE 'Complete referential integrity established for SMS-related tables.';
        
        IF auth_table_exists THEN
            RAISE NOTICE 'Auth table constraints also added for user_id references.';
        ELSE
            RAISE NOTICE 'Note: Auth table not found - auth constraints skipped.';
        END IF;
    ELSE
        RAISE NOTICE '⚠ WARNING: Some orphaned data remains - partial FK success';
    END IF;
    
    RAISE NOTICE 'Note: api_keys table has no user_id column - no FK needed';
    RAISE NOTICE 'Note: credit_purchases (empty), transcript_jobs (doesn''t exist) - skipped';
END $$;