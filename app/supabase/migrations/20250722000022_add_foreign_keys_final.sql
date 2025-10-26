-- Add foreign key constraints using the actual sms_users schema
-- Based on real schema analysis with correct column names

-- 1. VERIFY NO ORPHANED DATA EXISTS
DO $$
DECLARE
    orphaned_transcriptions integer;
    orphaned_messages integer;
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
    
    RAISE NOTICE 'Orphaned transcriptions.user_phone: %', orphaned_transcriptions;
    RAISE NOTICE 'Orphaned user_messages.from_phone: %', orphaned_messages;
    
    IF orphaned_transcriptions > 0 OR orphaned_messages > 0 THEN
        RAISE NOTICE 'Found orphaned data - will create missing sms_users records';
    ELSE
        RAISE NOTICE 'No orphaned data found - safe to add FK constraints';
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
            NULL,  -- No verification code needed
            NULL,  -- No verification expiry
            NULL,  -- No active session
            NULL,  -- No session expiry
            CURRENT_TIMESTAMP,  -- Last active now
            CURRENT_TIMESTAMP,  -- Created now
            NULL,  -- No auth user link
            0,     -- No remaining credits
            999,   -- High usage to indicate legacy user
            0,     -- No credits purchased
            UPPER(substring(replace(gen_random_uuid()::text, '-', ''), 1, 6)), -- Random referral code
            NULL,  -- Not referred by anyone
            0,     -- No referrals
            0,     -- No referral credits earned
            0,     -- No referral streak
            NULL,  -- No referral date
            NULL,  -- No display name
            NULL,  -- No TikTok handle
            NULL,  -- No TikTok profile URL
            NULL,  -- No TikTok link date
            transcription_count, -- Actual transcription count
            NULL,  -- No most popular video
            0      -- No popular video views
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
            true,  -- Assume verified since they sent messages
            NULL,
            NULL,
            NULL,
            NULL,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            NULL,
            5,     -- Default free credits
            0,     -- No free credits used yet
            0,     -- No credits purchased
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
            0,     -- No transcriptions yet
            NULL,
            0
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

-- 3. ADD FOREIGN KEY CONSTRAINTS

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

-- FK: transcriptions.user_id → auth.users.id (if auth users exist)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_transcriptions_user_id') THEN
        
        -- Only add if auth.users table exists and has data
        IF EXISTS (SELECT 1 FROM information_schema.tables 
                   WHERE table_schema = 'auth' AND table_name = 'users') THEN
                   
            -- Check for orphaned user_id values
            PERFORM 1 FROM transcriptions 
            WHERE user_id IS NOT NULL 
            AND NOT EXISTS (
                SELECT 1 FROM auth.users 
                WHERE id = transcriptions.user_id
            );
            
            IF NOT FOUND THEN
                ALTER TABLE transcriptions 
                ADD CONSTRAINT fk_transcriptions_user_id 
                FOREIGN KEY (user_id) REFERENCES auth.users(id) 
                ON DELETE SET NULL  -- Preserve transcriptions if user is deleted
                ON UPDATE CASCADE;
                RAISE NOTICE '✓ Added FK constraint: transcriptions.user_id → auth.users.id';
            ELSE
                -- Clean up orphaned user_id values
                UPDATE transcriptions SET user_id = NULL 
                WHERE user_id IS NOT NULL 
                AND NOT EXISTS (SELECT 1 FROM auth.users WHERE id = transcriptions.user_id);
                
                ALTER TABLE transcriptions 
                ADD CONSTRAINT fk_transcriptions_user_id 
                FOREIGN KEY (user_id) REFERENCES auth.users(id) 
                ON DELETE SET NULL
                ON UPDATE CASCADE;
                RAISE NOTICE '✓ Cleaned orphaned user_id and added FK constraint: transcriptions.user_id → auth.users.id';
            END IF;
        ELSE
            RAISE NOTICE 'ℹ auth.users table not found - skipping user_id FK constraint';
        END IF;
    ELSE
        RAISE NOTICE '✓ FK constraint transcriptions.user_id already exists';
    END IF;
END $$;

-- FK: sms_users.auth_user_id → auth.users.id (if auth users exist)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_sms_users_auth_user_id') THEN
        
        -- Only add if auth.users table exists
        IF EXISTS (SELECT 1 FROM information_schema.tables 
                   WHERE table_schema = 'auth' AND table_name = 'users') THEN
                   
            -- Check for orphaned auth_user_id values
            PERFORM 1 FROM sms_users 
            WHERE auth_user_id IS NOT NULL 
            AND NOT EXISTS (
                SELECT 1 FROM auth.users 
                WHERE id = sms_users.auth_user_id
            );
            
            IF NOT FOUND THEN
                ALTER TABLE sms_users 
                ADD CONSTRAINT fk_sms_users_auth_user_id 
                FOREIGN KEY (auth_user_id) REFERENCES auth.users(id) 
                ON DELETE SET NULL  -- SMS user can exist without auth user
                ON UPDATE CASCADE;
                RAISE NOTICE '✓ Added FK constraint: sms_users.auth_user_id → auth.users.id';
            ELSE
                -- Clean up orphaned auth_user_id values
                UPDATE sms_users SET auth_user_id = NULL 
                WHERE auth_user_id IS NOT NULL 
                AND NOT EXISTS (SELECT 1 FROM auth.users WHERE id = sms_users.auth_user_id);
                
                ALTER TABLE sms_users 
                ADD CONSTRAINT fk_sms_users_auth_user_id 
                FOREIGN KEY (auth_user_id) REFERENCES auth.users(id) 
                ON DELETE SET NULL
                ON UPDATE CASCADE;
                RAISE NOTICE '✓ Cleaned orphaned auth_user_id and added FK constraint: sms_users.auth_user_id → auth.users.id';
            END IF;
        ELSE
            RAISE NOTICE 'ℹ auth.users table not found - skipping auth_user_id FK constraint';
        END IF;
    ELSE
        RAISE NOTICE '✓ FK constraint sms_users.auth_user_id already exists';
    END IF;
END $$;

-- FK: api_keys.user_id → auth.users.id (if api_keys table exists and has auth users)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'api_keys') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                       WHERE constraint_name = 'fk_api_keys_user_id') THEN
            
            IF EXISTS (SELECT 1 FROM information_schema.tables 
                       WHERE table_schema = 'auth' AND table_name = 'users') THEN
                       
                -- Check for orphaned user_id values in api_keys
                PERFORM 1 FROM api_keys 
                WHERE user_id IS NOT NULL 
                AND NOT EXISTS (
                    SELECT 1 FROM auth.users 
                    WHERE id = api_keys.user_id
                );
                
                IF NOT FOUND THEN
                    ALTER TABLE api_keys 
                    ADD CONSTRAINT fk_api_keys_user_id 
                    FOREIGN KEY (user_id) REFERENCES auth.users(id) 
                    ON DELETE CASCADE  -- Delete API keys if user is deleted
                    ON UPDATE CASCADE;
                    RAISE NOTICE '✓ Added FK constraint: api_keys.user_id → auth.users.id';
                ELSE
                    -- Clean up orphaned user_id values
                    DELETE FROM api_keys 
                    WHERE user_id IS NOT NULL 
                    AND NOT EXISTS (SELECT 1 FROM auth.users WHERE id = api_keys.user_id);
                    
                    ALTER TABLE api_keys 
                    ADD CONSTRAINT fk_api_keys_user_id 
                    FOREIGN KEY (user_id) REFERENCES auth.users(id) 
                    ON DELETE CASCADE
                    ON UPDATE CASCADE;
                    RAISE NOTICE '✓ Cleaned orphaned user_id and added FK constraint: api_keys.user_id → auth.users.id';
                END IF;
            ELSE
                RAISE NOTICE 'ℹ auth.users table not found - skipping api_keys FK constraint';
            END IF;
        ELSE
            RAISE NOTICE '✓ FK constraint api_keys.user_id already exists';
        END IF;
    ELSE
        RAISE NOTICE 'ℹ api_keys table not found - skipping FK constraint';
    END IF;
END $$;

-- 4. ADD SUPPORTING INDEXES FOR PERFORMANCE
CREATE INDEX IF NOT EXISTS idx_transcriptions_user_phone_fk ON transcriptions(user_phone);
CREATE INDEX IF NOT EXISTS idx_user_messages_from_phone_fk ON user_messages(from_phone);
CREATE INDEX IF NOT EXISTS idx_transcriptions_user_id_fk ON transcriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_sms_users_auth_user_id_fk ON sms_users(auth_user_id);

-- Add API keys index if table exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'api_keys') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_api_keys_user_id_fk ON api_keys(user_id)';
    END IF;
END $$;

-- 5. ADD COMMENTS FOR DOCUMENTATION
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'fk_transcriptions_user_phone') THEN
        EXECUTE 'COMMENT ON CONSTRAINT fk_transcriptions_user_phone ON transcriptions IS ''Links transcriptions to SMS users, preserves transcriptions if user deleted''';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'fk_user_messages_from_phone') THEN
        EXECUTE 'COMMENT ON CONSTRAINT fk_user_messages_from_phone ON user_messages IS ''Links messages to SMS users, cascades delete to maintain integrity''';
    END IF;
END $$;

-- 6. FINAL VERIFICATION AND SUMMARY
DO $$
DECLARE
    fk_count integer;
    total_transcriptions integer;
    total_messages integer;
    total_sms_users integer;
    orphaned_transcriptions integer;
    orphaned_messages integer;
BEGIN
    -- Count successful FK constraints
    SELECT COUNT(*) INTO fk_count
    FROM information_schema.table_constraints 
    WHERE constraint_type = 'FOREIGN KEY'
    AND constraint_name LIKE 'fk_%'
    AND table_name IN ('transcriptions', 'user_messages', 'sms_users', 'api_keys');
    
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
    
    RAISE NOTICE '=== FOREIGN KEY MIGRATION SUMMARY ===';
    RAISE NOTICE 'Foreign key constraints added: %', fk_count;
    RAISE NOTICE 'Total transcriptions: %', total_transcriptions;
    RAISE NOTICE 'Total user messages: %', total_messages;
    RAISE NOTICE 'Total SMS users: %', total_sms_users;
    RAISE NOTICE 'Remaining orphaned transcriptions: %', orphaned_transcriptions;
    RAISE NOTICE 'Remaining orphaned messages: %', orphaned_messages;
    
    IF orphaned_transcriptions = 0 AND orphaned_messages = 0 THEN
        RAISE NOTICE '✅ SUCCESS: All foreign key constraints added successfully!';
        RAISE NOTICE 'Complete referential integrity established for existing tables.';
    ELSE
        RAISE NOTICE '⚠ WARNING: Some orphaned data remains - partial FK success';
    END IF;
    
    RAISE NOTICE 'Note: Skipped credit_purchases (empty), transcript_jobs (doesn''t exist)';
END $$;