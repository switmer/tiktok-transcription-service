-- Clean up orphaned data before adding foreign key constraints
-- This fixes the FK constraint violation by handling orphaned records

-- 1. ANALYZE THE ORPHANED DATA FIRST
DO $$
BEGIN
    RAISE NOTICE 'Analyzing orphaned data before cleanup...';
END $$;

-- Check orphaned transcriptions.user_phone records
SELECT 
    'ORPHANED TRANSCRIPTIONS' as issue_type,
    COUNT(*) as count,
    array_agg(DISTINCT user_phone) as orphaned_phones
FROM transcriptions 
WHERE user_phone IS NOT NULL 
AND NOT EXISTS (
    SELECT 1 FROM sms_users 
    WHERE phone_number = transcriptions.user_phone
);

-- Check orphaned credit_purchases.user_phone records  
SELECT 
    'ORPHANED CREDIT PURCHASES' as issue_type,
    COUNT(*) as count,
    array_agg(DISTINCT user_phone) as orphaned_phones
FROM credit_purchases 
WHERE user_phone IS NOT NULL 
AND NOT EXISTS (
    SELECT 1 FROM sms_users 
    WHERE phone_number = credit_purchases.user_phone
);

-- 2. OPTION 1: CREATE MISSING SMS_USERS RECORDS (RECOMMENDED)
-- This preserves all data by creating placeholder SMS user records

DO $$
DECLARE
    orphaned_phone text;
    created_count integer := 0;
BEGIN
    RAISE NOTICE 'Creating missing sms_users records for orphaned phone numbers...';
    
    -- Create sms_users records for orphaned transcriptions.user_phone
    FOR orphaned_phone IN 
        SELECT DISTINCT t.user_phone
        FROM transcriptions t
        WHERE t.user_phone IS NOT NULL 
        AND NOT EXISTS (
            SELECT 1 FROM sms_users s 
            WHERE s.phone_number = t.user_phone
        )
    LOOP
        -- Insert missing sms_user record
        INSERT INTO sms_users (
            id,
            phone_number,
            phone_verified,
            credits_remaining,
            free_credits_used,
            total_transcriptions,
            monthly_transcriptions,
            referral_code,
            referrals_count,
            last_active,
            created_at,
            updated_at
        ) VALUES (
            gen_random_uuid(),
            orphaned_phone,
            true,  -- Assume verified since they have transcriptions
            0,     -- No remaining credits (they used the system somehow)
            999,   -- High usage to indicate legacy user
            (SELECT COUNT(*) FROM transcriptions WHERE user_phone = orphaned_phone),
            (SELECT COUNT(*) FROM transcriptions WHERE user_phone = orphaned_phone 
             AND created_at >= date_trunc('month', CURRENT_DATE)),
            UPPER(substring(replace(gen_random_uuid()::text, '-', ''), 1, 6)), -- Random referral code
            0,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (phone_number) DO NOTHING; -- Skip if somehow already exists
        
        created_count := created_count + 1;
        RAISE NOTICE 'Created sms_users record for phone: %', orphaned_phone;
    END LOOP;
    
    -- Create sms_users records for orphaned credit_purchases.user_phone  
    FOR orphaned_phone IN 
        SELECT DISTINCT cp.user_phone
        FROM credit_purchases cp
        WHERE cp.user_phone IS NOT NULL 
        AND NOT EXISTS (
            SELECT 1 FROM sms_users s 
            WHERE s.phone_number = cp.user_phone
        )
        AND NOT EXISTS (
            SELECT 1 FROM transcriptions t
            WHERE t.user_phone = cp.user_phone  -- Skip if already handled above
        )
    LOOP
        -- Insert missing sms_user record for credit purchaser
        INSERT INTO sms_users (
            id,
            phone_number,
            phone_verified,
            credits_remaining,
            free_credits_used,
            total_transcriptions,
            monthly_transcriptions,
            referral_code,
            referrals_count,
            last_active,
            created_at,
            updated_at
        ) VALUES (
            gen_random_uuid(),
            orphaned_phone,
            true,  -- Assume verified since they purchased credits
            (SELECT COALESCE(SUM(credits_purchased), 0) FROM credit_purchases WHERE user_phone = orphaned_phone),
            0,     -- No free credits used
            0,     -- No transcriptions yet
            0,     -- No transcriptions this month
            UPPER(substring(replace(gen_random_uuid()::text, '-', ''), 1, 6)), -- Random referral code
            0,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (phone_number) DO NOTHING;
        
        created_count := created_count + 1;
        RAISE NOTICE 'Created sms_users record for credit purchaser: %', orphaned_phone;
    END LOOP;
    
    RAISE NOTICE 'Created % missing sms_users records', created_count;
END $$;

-- 3. VERIFY THE CLEANUP
DO $$
DECLARE
    orphaned_transcriptions integer;
    orphaned_purchases integer;
BEGIN
    -- Count remaining orphaned records
    SELECT COUNT(*) INTO orphaned_transcriptions
    FROM transcriptions 
    WHERE user_phone IS NOT NULL 
    AND NOT EXISTS (
        SELECT 1 FROM sms_users 
        WHERE phone_number = transcriptions.user_phone
    );
    
    SELECT COUNT(*) INTO orphaned_purchases
    FROM credit_purchases 
    WHERE user_phone IS NOT NULL 
    AND NOT EXISTS (
        SELECT 1 FROM sms_users 
        WHERE phone_number = credit_purchases.user_phone
    );
    
    RAISE NOTICE 'After cleanup: % orphaned transcriptions, % orphaned purchases', 
                 orphaned_transcriptions, orphaned_purchases;
    
    IF orphaned_transcriptions = 0 AND orphaned_purchases = 0 THEN
        RAISE NOTICE '✓ All orphaned data resolved! Ready for foreign key constraints.';
    ELSE
        RAISE NOTICE '⚠ Still have orphaned data - FK constraints will fail';
    END IF;
END $$;

-- 4. ALTERNATIVE OPTION: NULL OUT ORPHANED REFERENCES (UNCOMMENT IF PREFERRED)
-- This approach sets orphaned foreign keys to NULL instead of creating missing records

/*
DO $$
DECLARE
    nulled_transcriptions integer;
    nulled_purchases integer;
BEGIN
    RAISE NOTICE 'Alternative: Setting orphaned foreign keys to NULL...';
    
    -- NULL out orphaned transcriptions.user_phone
    UPDATE transcriptions 
    SET user_phone = NULL
    WHERE user_phone IS NOT NULL 
    AND NOT EXISTS (
        SELECT 1 FROM sms_users 
        WHERE phone_number = transcriptions.user_phone
    );
    GET DIAGNOSTICS nulled_transcriptions = ROW_COUNT;
    
    -- NULL out orphaned credit_purchases.user_phone
    UPDATE credit_purchases 
    SET user_phone = NULL
    WHERE user_phone IS NOT NULL 
    AND NOT EXISTS (
        SELECT 1 FROM sms_users 
        WHERE phone_number = credit_purchases.user_phone
    );
    GET DIAGNOSTICS nulled_purchases = ROW_COUNT;
    
    RAISE NOTICE 'Set % transcriptions.user_phone to NULL', nulled_transcriptions;
    RAISE NOTICE 'Set % credit_purchases.user_phone to NULL', nulled_purchases;
END $$;
*/

-- 5. FINAL SUMMARY
SELECT 
    'SUMMARY' as status,
    (SELECT COUNT(*) FROM sms_users) as total_sms_users,
    (SELECT COUNT(*) FROM transcriptions WHERE user_phone IS NOT NULL) as transcriptions_with_phone,
    (SELECT COUNT(*) FROM credit_purchases WHERE user_phone IS NOT NULL) as purchases_with_phone;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '🧹 Orphaned data cleanup completed!';
    RAISE NOTICE 'Created missing sms_users records to preserve referential integrity';
    RAISE NOTICE 'You can now run the foreign key constraints migration safely';
END $$;