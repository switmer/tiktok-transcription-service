-- Safely add foreign key constraints after cleaning up orphaned data
-- This version includes built-in orphaned data handling

-- 1. FINAL CLEANUP: Handle any remaining orphaned data inline
DO $$
DECLARE
    orphaned_count integer;
BEGIN
    -- Check for orphaned transcriptions.user_phone
    SELECT COUNT(*) INTO orphaned_count
    FROM transcriptions 
    WHERE user_phone IS NOT NULL 
    AND NOT EXISTS (
        SELECT 1 FROM sms_users 
        WHERE phone_number = transcriptions.user_phone
    );
    
    IF orphaned_count > 0 THEN
        RAISE NOTICE 'Found % orphaned transcriptions.user_phone records - creating missing sms_users', orphaned_count;
        
        -- Create missing sms_users records for orphaned transcriptions
        INSERT INTO sms_users (
            id, phone_number, phone_verified, credits_remaining, 
            free_credits_used, total_transcriptions, monthly_transcriptions,
            referral_code, referrals_count, last_active, created_at, updated_at
        )
        SELECT DISTINCT
            gen_random_uuid(),
            t.user_phone,
            true,
            0,
            999, -- Mark as legacy user
            COUNT(*) OVER (PARTITION BY t.user_phone),
            0,
            UPPER(substring(replace(gen_random_uuid()::text, '-', ''), 1, 6)),
            0,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM transcriptions t
        WHERE t.user_phone IS NOT NULL 
        AND NOT EXISTS (
            SELECT 1 FROM sms_users s 
            WHERE s.phone_number = t.user_phone
        )
        ON CONFLICT (phone_number) DO NOTHING;
    END IF;
    
    -- Check for orphaned credit_purchases.user_phone
    SELECT COUNT(*) INTO orphaned_count
    FROM credit_purchases 
    WHERE user_phone IS NOT NULL 
    AND NOT EXISTS (
        SELECT 1 FROM sms_users 
        WHERE phone_number = credit_purchases.user_phone
    );
    
    IF orphaned_count > 0 THEN
        RAISE NOTICE 'Found % orphaned credit_purchases.user_phone records - creating missing sms_users', orphaned_count;
        
        -- Create missing sms_users records for orphaned credit purchases
        INSERT INTO sms_users (
            id, phone_number, phone_verified, credits_remaining, 
            free_credits_used, total_transcriptions, monthly_transcriptions,
            referral_code, referrals_count, last_active, created_at, updated_at
        )
        SELECT DISTINCT
            gen_random_uuid(),
            cp.user_phone,
            true,
            COALESCE(SUM(cp.credits_purchased) OVER (PARTITION BY cp.user_phone), 0),
            0,
            0,
            0,
            UPPER(substring(replace(gen_random_uuid()::text, '-', ''), 1, 6)),
            0,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM credit_purchases cp
        WHERE cp.user_phone IS NOT NULL 
        AND NOT EXISTS (
            SELECT 1 FROM sms_users s 
            WHERE s.phone_number = cp.user_phone
        )
        ON CONFLICT (phone_number) DO NOTHING;
    END IF;
END $$;

-- 2. ADD FOREIGN KEY CONSTRAINTS (SAFE VERSION)

-- FK: transcriptions.user_phone → sms_users.phone_number
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_transcriptions_user_phone') THEN
        
        -- Final verification before adding constraint
        PERFORM 1 FROM transcriptions 
        WHERE user_phone IS NOT NULL 
        AND NOT EXISTS (
            SELECT 1 FROM sms_users 
            WHERE phone_number = transcriptions.user_phone
        );
        
        IF NOT FOUND THEN
            ALTER TABLE transcriptions 
            ADD CONSTRAINT fk_transcriptions_user_phone 
            FOREIGN KEY (user_phone) REFERENCES sms_users(phone_number) 
            ON DELETE SET NULL
            ON UPDATE CASCADE;
            RAISE NOTICE '✓ Added FK constraint: transcriptions.user_phone → sms_users.phone_number';
        ELSE
            RAISE NOTICE '⚠ Still have orphaned transcriptions.user_phone - skipping FK constraint';
        END IF;
    ELSE
        RAISE NOTICE '✓ FK constraint transcriptions.user_phone already exists';
    END IF;
END $$;

-- FK: credit_purchases.user_phone → sms_users.phone_number
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_credit_purchases_user_phone') THEN
        
        -- Final verification before adding constraint
        PERFORM 1 FROM credit_purchases 
        WHERE user_phone IS NOT NULL 
        AND NOT EXISTS (
            SELECT 1 FROM sms_users 
            WHERE phone_number = credit_purchases.user_phone
        );
        
        IF NOT FOUND THEN
            ALTER TABLE credit_purchases 
            ADD CONSTRAINT fk_credit_purchases_user_phone 
            FOREIGN KEY (user_phone) REFERENCES sms_users(phone_number) 
            ON DELETE CASCADE
            ON UPDATE CASCADE;
            RAISE NOTICE '✓ Added FK constraint: credit_purchases.user_phone → sms_users.phone_number';
        ELSE
            RAISE NOTICE '⚠ Still have orphaned credit_purchases.user_phone - skipping FK constraint';
        END IF;
    ELSE
        RAISE NOTICE '✓ FK constraint credit_purchases.user_phone already exists';
    END IF;
END $$;

-- FK: user_messages.from_phone → sms_users.phone_number (if table exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'user_messages') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                       WHERE constraint_name = 'fk_user_messages_from_phone') THEN
            
            -- Check for orphaned data first
            PERFORM 1 FROM user_messages 
            WHERE from_phone IS NOT NULL 
            AND NOT EXISTS (
                SELECT 1 FROM sms_users 
                WHERE phone_number = user_messages.from_phone
            );
            
            IF NOT FOUND THEN
                ALTER TABLE user_messages 
                ADD CONSTRAINT fk_user_messages_from_phone 
                FOREIGN KEY (from_phone) REFERENCES sms_users(phone_number) 
                ON DELETE CASCADE
                ON UPDATE CASCADE;
                RAISE NOTICE '✓ Added FK constraint: user_messages.from_phone → sms_users.phone_number';
            ELSE
                RAISE NOTICE '⚠ Found orphaned user_messages.from_phone - skipping FK constraint';
            END IF;
        ELSE
            RAISE NOTICE '✓ FK constraint user_messages.from_phone already exists';
        END IF;
    ELSE
        RAISE NOTICE 'ℹ user_messages table does not exist - skipping FK constraint';
    END IF;
END $$;

-- FK: transcript_jobs.from_phone → sms_users.phone_number (if table exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                       WHERE constraint_name = 'fk_transcript_jobs_from_phone') THEN
            
            -- Check for orphaned data first
            PERFORM 1 FROM transcript_jobs 
            WHERE from_phone IS NOT NULL 
            AND NOT EXISTS (
                SELECT 1 FROM sms_users 
                WHERE phone_number = transcript_jobs.from_phone
            );
            
            IF NOT FOUND THEN
                ALTER TABLE transcript_jobs 
                ADD CONSTRAINT fk_transcript_jobs_from_phone 
                FOREIGN KEY (from_phone) REFERENCES sms_users(phone_number) 
                ON DELETE CASCADE
                ON UPDATE CASCADE;
                RAISE NOTICE '✓ Added FK constraint: transcript_jobs.from_phone → sms_users.phone_number';
            ELSE
                RAISE NOTICE '⚠ Found orphaned transcript_jobs.from_phone - skipping FK constraint';
            END IF;
        ELSE
            RAISE NOTICE '✓ FK constraint transcript_jobs.from_phone already exists';
        END IF;
    ELSE
        RAISE NOTICE 'ℹ transcript_jobs table does not exist - skipping FK constraint';
    END IF;
END $$;

-- FK: transcript_jobs.transcript_id → transcriptions.task_id (if table exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        -- Drop existing constraint if it exists (to recreate with better cascade behavior)
        IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_transcript_jobs_transcript_id') THEN
            ALTER TABLE transcript_jobs DROP CONSTRAINT fk_transcript_jobs_transcript_id;
        END IF;
        
        -- Check for orphaned data first
        PERFORM 1 FROM transcript_jobs 
        WHERE transcript_id IS NOT NULL 
        AND NOT EXISTS (
            SELECT 1 FROM transcriptions 
            WHERE task_id = transcript_jobs.transcript_id
        );
        
        IF NOT FOUND THEN
            ALTER TABLE transcript_jobs 
            ADD CONSTRAINT fk_transcript_jobs_transcript_id 
            FOREIGN KEY (transcript_id) REFERENCES transcriptions(task_id) 
            ON DELETE CASCADE
            ON UPDATE CASCADE;
            RAISE NOTICE '✓ Added FK constraint: transcript_jobs.transcript_id → transcriptions.task_id';
        ELSE
            RAISE NOTICE '⚠ Found orphaned transcript_jobs.transcript_id - skipping FK constraint';
        END IF;
    ELSE
        RAISE NOTICE 'ℹ transcript_jobs table does not exist - skipping FK constraint';
    END IF;
END $$;

-- FK: api_keys.user_id → auth.users.id
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_api_keys_user_id') THEN
        
        -- Check for orphaned data first
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
            ON DELETE CASCADE
            ON UPDATE CASCADE;
            RAISE NOTICE '✓ Added FK constraint: api_keys.user_id → auth.users.id';
        ELSE
            RAISE NOTICE '⚠ Found orphaned api_keys.user_id - skipping FK constraint';
        END IF;
    ELSE
        RAISE NOTICE '✓ FK constraint api_keys.user_id already exists';
    END IF;
END $$;

-- FK: transcriptions.user_id → auth.users.id
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_transcriptions_user_id') THEN
        
        -- Check for orphaned data first
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
            ON DELETE SET NULL
            ON UPDATE CASCADE;
            RAISE NOTICE '✓ Added FK constraint: transcriptions.user_id → auth.users.id';
        ELSE
            RAISE NOTICE '⚠ Found orphaned transcriptions.user_id - skipping FK constraint';
        END IF;
    ELSE
        RAISE NOTICE '✓ FK constraint transcriptions.user_id already exists';
    END IF;
END $$;

-- FK: sms_users.auth_user_id → auth.users.id
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_sms_users_auth_user_id') THEN
        
        -- Check for orphaned data first
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
            ON DELETE SET NULL
            ON UPDATE CASCADE;
            RAISE NOTICE '✓ Added FK constraint: sms_users.auth_user_id → auth.users.id';
        ELSE
            RAISE NOTICE '⚠ Found orphaned sms_users.auth_user_id - skipping FK constraint';
        END IF;
    ELSE
        RAISE NOTICE '✓ FK constraint sms_users.auth_user_id already exists';
    END IF;
END $$;

-- 3. ADD SUPPORTING INDEXES
CREATE INDEX IF NOT EXISTS idx_transcriptions_user_phone_fk ON transcriptions(user_phone);
CREATE INDEX IF NOT EXISTS idx_credit_purchases_user_phone_fk ON credit_purchases(user_phone);
CREATE INDEX IF NOT EXISTS idx_transcriptions_user_id_fk ON transcriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_sms_users_auth_user_id_fk ON sms_users(auth_user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_user_id_fk ON api_keys(user_id);

-- Create conditional indexes for optional tables
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'user_messages') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_user_messages_from_phone_fk ON user_messages(from_phone)';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_transcript_jobs_from_phone_fk ON transcript_jobs(from_phone)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_transcript_jobs_transcript_id_fk ON transcript_jobs(transcript_id)';
    END IF;
END $$;

-- 4. FINAL VERIFICATION
DO $$
DECLARE
    fk_count integer;
    orphaned_transcriptions integer;
    orphaned_purchases integer;
BEGIN
    -- Count successful FK constraints
    SELECT COUNT(*) INTO fk_count
    FROM information_schema.table_constraints 
    WHERE constraint_type = 'FOREIGN KEY'
    AND constraint_name LIKE 'fk_%'
    AND table_name IN ('transcriptions', 'credit_purchases', 'user_messages', 'transcript_jobs', 'api_keys', 'sms_users');
    
    -- Check remaining orphaned data
    SELECT COUNT(*) INTO orphaned_transcriptions
    FROM transcriptions 
    WHERE user_phone IS NOT NULL 
    AND NOT EXISTS (SELECT 1 FROM sms_users WHERE phone_number = transcriptions.user_phone);
    
    SELECT COUNT(*) INTO orphaned_purchases
    FROM credit_purchases 
    WHERE user_phone IS NOT NULL 
    AND NOT EXISTS (SELECT 1 FROM sms_users WHERE phone_number = credit_purchases.user_phone);
    
    RAISE NOTICE '=== FOREIGN KEY MIGRATION SUMMARY ===';
    RAISE NOTICE 'Foreign key constraints added: %', fk_count;
    RAISE NOTICE 'Remaining orphaned transcriptions: %', orphaned_transcriptions;
    RAISE NOTICE 'Remaining orphaned purchases: %', orphaned_purchases;
    
    IF orphaned_transcriptions = 0 AND orphaned_purchases = 0 THEN
        RAISE NOTICE '✅ SUCCESS: All foreign key constraints added successfully!';
    ELSE
        RAISE NOTICE '⚠ WARNING: Some orphaned data remains - partial FK success';
    END IF;
END $$;