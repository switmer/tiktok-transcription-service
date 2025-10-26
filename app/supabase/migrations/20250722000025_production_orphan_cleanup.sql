-- PRODUCTION-GRADE ORPHAN CLEANUP AND FK CONSTRAINT MIGRATION
-- Step 1: Comprehensive orphan detection and cleanup before adding FK constraints
-- Based on actual TypeScript schema analysis

-- ===========================================
-- 1. ORPHAN DETECTION AND ANALYSIS
-- ===========================================

-- Create temporary table to track cleanup actions
CREATE TEMP TABLE cleanup_log (
    step_name text,
    table_name text,
    action text,
    record_count integer,
    details text,
    timestamp timestamptz DEFAULT CURRENT_TIMESTAMP
);

-- Function to log cleanup actions
CREATE OR REPLACE FUNCTION log_cleanup_action(
    step text, 
    tbl text, 
    act text, 
    cnt integer, 
    det text DEFAULT NULL
) RETURNS void AS $$
BEGIN
    INSERT INTO cleanup_log (step_name, table_name, action, record_count, details)
    VALUES (step, tbl, act, cnt, det);
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    orphaned_transcriptions integer;
    orphaned_messages integer;
    orphaned_purchases integer;
    orphaned_referrals integer;
    total_sms_users integer;
BEGIN
    RAISE NOTICE '=== PRODUCTION ORPHAN ANALYSIS ===';
    
    -- Get baseline counts
    SELECT COUNT(*) INTO total_sms_users FROM sms_users;
    PERFORM log_cleanup_action('BASELINE', 'sms_users', 'COUNT', total_sms_users);
    
    -- Check orphaned transcriptions.user_phone
    SELECT COUNT(*) INTO orphaned_transcriptions
    FROM transcriptions 
    WHERE user_phone IS NOT NULL 
    AND user_phone NOT IN (SELECT phone_number FROM sms_users WHERE phone_number IS NOT NULL);
    
    PERFORM log_cleanup_action('ORPHAN_CHECK', 'transcriptions', 'user_phone_orphans', orphaned_transcriptions);
    
    -- Check orphaned user_messages.from_phone
    SELECT COUNT(*) INTO orphaned_messages
    FROM user_messages 
    WHERE from_phone IS NOT NULL 
    AND from_phone NOT IN (SELECT phone_number FROM sms_users WHERE phone_number IS NOT NULL);
    
    PERFORM log_cleanup_action('ORPHAN_CHECK', 'user_messages', 'from_phone_orphans', orphaned_messages);
    
    -- Check orphaned credit_purchases.phone_number
    SELECT COUNT(*) INTO orphaned_purchases
    FROM credit_purchases 
    WHERE phone_number IS NOT NULL 
    AND phone_number NOT IN (SELECT phone_number FROM sms_users WHERE phone_number IS NOT NULL);
    
    PERFORM log_cleanup_action('ORPHAN_CHECK', 'credit_purchases', 'phone_number_orphans', orphaned_purchases);
    
    -- Check orphaned pending_referrals.referral_code
    SELECT COUNT(*) INTO orphaned_referrals
    FROM pending_referrals 
    WHERE referral_code IS NOT NULL 
    AND referral_code NOT IN (SELECT referral_code FROM sms_users WHERE referral_code IS NOT NULL);
    
    PERFORM log_cleanup_action('ORPHAN_CHECK', 'pending_referrals', 'referral_code_orphans', orphaned_referrals);
    
    -- Summary
    RAISE NOTICE 'Total SMS users: %', total_sms_users;
    RAISE NOTICE 'Orphaned transcriptions.user_phone: %', orphaned_transcriptions;
    RAISE NOTICE 'Orphaned user_messages.from_phone: %', orphaned_messages;
    RAISE NOTICE 'Orphaned credit_purchases.phone_number: %', orphaned_purchases;
    RAISE NOTICE 'Orphaned pending_referrals.referral_code: %', orphaned_referrals;
    
    IF orphaned_transcriptions = 0 AND orphaned_messages = 0 AND orphaned_purchases = 0 THEN
        RAISE NOTICE '✅ No critical orphans found - ready for FK constraints!';
    ELSE
        RAISE NOTICE '⚠️ Orphans detected - will create missing SMS users';
    END IF;
END $$;

-- ===========================================
-- 2. SHOW SAMPLE ORPHANED DATA FOR REVIEW
-- ===========================================

-- Show sample orphaned transcriptions
DO $$
DECLARE
    sample_rec RECORD;
    count_shown integer := 0;
BEGIN
    RAISE NOTICE '=== SAMPLE ORPHANED TRANSCRIPTIONS ===';
    
    FOR sample_rec IN
        SELECT task_id, user_phone, title, created_at
        FROM transcriptions 
        WHERE user_phone IS NOT NULL 
        AND user_phone NOT IN (SELECT phone_number FROM sms_users WHERE phone_number IS NOT NULL)
        ORDER BY created_at DESC
        LIMIT 5
    LOOP
        RAISE NOTICE 'Orphan: task_id=%, phone=%, title=%, created=%', 
                     sample_rec.task_id, sample_rec.user_phone, 
                     LEFT(sample_rec.title, 50), sample_rec.created_at;
        count_shown := count_shown + 1;
    END LOOP;
    
    IF count_shown = 0 THEN
        RAISE NOTICE 'No orphaned transcriptions to show';
    END IF;
END $$;

-- Show sample orphaned messages
DO $$
DECLARE
    sample_rec RECORD;
    count_shown integer := 0;
BEGIN
    RAISE NOTICE '=== SAMPLE ORPHANED USER MESSAGES ===';
    
    FOR sample_rec IN
        SELECT id, from_phone, LEFT(message_body, 50) as message_preview, created_at
        FROM user_messages 
        WHERE from_phone IS NOT NULL 
        AND from_phone NOT IN (SELECT phone_number FROM sms_users WHERE phone_number IS NOT NULL)
        ORDER BY created_at DESC
        LIMIT 5
    LOOP
        RAISE NOTICE 'Orphan: id=%, phone=%, message=%, created=%', 
                     sample_rec.id, sample_rec.from_phone, 
                     sample_rec.message_preview, sample_rec.created_at;
        count_shown := count_shown + 1;
    END LOOP;
    
    IF count_shown = 0 THEN
        RAISE NOTICE 'No orphaned user messages to show';
    END IF;
END $$;

-- ===========================================
-- 3. PRODUCTION CLEANUP STRATEGY
-- ===========================================

-- Create missing SMS users for orphaned data (preserves all historical data)
DO $$
DECLARE
    orphaned_phone text;
    created_count integer := 0;
    transcription_count integer;
    message_count integer;
    latest_activity timestamptz;
BEGIN
    RAISE NOTICE '=== CREATING MISSING SMS USERS (PRESERVING ALL DATA) ===';
    
    -- Strategy: Create SMS users for any phone number that appears in transcriptions or messages
    -- This ensures no data loss while establishing referential integrity
    
    FOR orphaned_phone IN 
        SELECT DISTINCT phone_num FROM (
            -- Get all orphaned phone numbers from transcriptions
            SELECT user_phone as phone_num
            FROM transcriptions 
            WHERE user_phone IS NOT NULL 
            AND user_phone NOT IN (SELECT phone_number FROM sms_users WHERE phone_number IS NOT NULL)
            
            UNION
            
            -- Get all orphaned phone numbers from user_messages
            SELECT from_phone as phone_num
            FROM user_messages 
            WHERE from_phone IS NOT NULL 
            AND from_phone NOT IN (SELECT phone_number FROM sms_users WHERE phone_number IS NOT NULL)
            
            UNION
            
            -- Get all orphaned phone numbers from credit_purchases
            SELECT phone_number as phone_num
            FROM credit_purchases 
            WHERE phone_number IS NOT NULL 
            AND phone_number NOT IN (SELECT phone_number FROM sms_users WHERE phone_number IS NOT NULL)
        ) all_orphans
        ORDER BY phone_num
    LOOP
        -- Calculate stats for this orphaned phone
        SELECT COUNT(*) INTO transcription_count 
        FROM transcriptions WHERE user_phone = orphaned_phone;
        
        SELECT COUNT(*) INTO message_count 
        FROM user_messages WHERE from_phone = orphaned_phone;
        
        -- Get latest activity date
        SELECT GREATEST(
            COALESCE(MAX(t.created_at), '1970-01-01'::timestamptz),
            COALESCE(MAX(m.created_at), '1970-01-01'::timestamptz)
        ) INTO latest_activity
        FROM transcriptions t 
        FULL OUTER JOIN user_messages m ON t.user_phone = m.from_phone
        WHERE COALESCE(t.user_phone, m.from_phone) = orphaned_phone;
        
        -- Create comprehensive SMS user record
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
            true,  -- Assume verified since they have historical activity
            NULL,
            NULL,
            NULL,
            NULL,
            latest_activity,
            latest_activity,  -- Set created_at to their first activity
            NULL,
            CASE 
                WHEN transcription_count > 0 THEN 0  -- Used credits for transcriptions
                ELSE 5  -- Default credits for message-only users
            END,
            GREATEST(transcription_count, 0),  -- Mark transcriptions as used free credits
            (SELECT COALESCE(SUM(credits_purchased), 0) FROM credit_purchases WHERE phone_number = orphaned_phone),
            UPPER(substring(replace(gen_random_uuid()::text, '-', ''), 1, 6)),  -- Generate referral code
            NULL,
            0,
            0,
            0,
            NULL,
            NULL,  -- No display name
            NULL,  -- No TikTok handle
            NULL,  -- No TikTok profile
            NULL,
            transcription_count,
            NULL,  -- No most popular video tracking
            0
        );
        
        created_count := created_count + 1;
        
        PERFORM log_cleanup_action(
            'CREATE_SMS_USER', 
            'sms_users', 
            'orphan_phone_recovery', 
            1, 
            format('phone=%s, transcriptions=%s, messages=%s', orphaned_phone, transcription_count, message_count)
        );
        
        RAISE NOTICE 'Created SMS user: % (% transcriptions, % messages)', 
                     orphaned_phone, transcription_count, message_count;
    END LOOP;
    
    PERFORM log_cleanup_action('CLEANUP_SUMMARY', 'sms_users', 'total_created', created_count);
    
    IF created_count > 0 THEN
        RAISE NOTICE '✅ Created % missing SMS users - all orphaned data preserved!', created_count;
    ELSE
        RAISE NOTICE '✅ No missing SMS users needed - data already clean!';
    END IF;
END $$;

-- ===========================================
-- 4. FINAL VERIFICATION BEFORE FK CONSTRAINTS
-- ===========================================

DO $$
DECLARE
    remaining_transcription_orphans integer;
    remaining_message_orphans integer;
    remaining_purchase_orphans integer;
    remaining_referral_orphans integer;
    total_sms_users_after integer;
BEGIN
    RAISE NOTICE '=== FINAL VERIFICATION BEFORE FK CONSTRAINTS ===';
    
    -- Recheck orphan counts after cleanup
    SELECT COUNT(*) INTO remaining_transcription_orphans
    FROM transcriptions 
    WHERE user_phone IS NOT NULL 
    AND user_phone NOT IN (SELECT phone_number FROM sms_users WHERE phone_number IS NOT NULL);
    
    SELECT COUNT(*) INTO remaining_message_orphans
    FROM user_messages 
    WHERE from_phone IS NOT NULL 
    AND from_phone NOT IN (SELECT phone_number FROM sms_users WHERE phone_number IS NOT NULL);
    
    SELECT COUNT(*) INTO remaining_purchase_orphans
    FROM credit_purchases 
    WHERE phone_number IS NOT NULL 
    AND phone_number NOT IN (SELECT phone_number FROM sms_users WHERE phone_number IS NOT NULL);
    
    SELECT COUNT(*) INTO remaining_referral_orphans
    FROM pending_referrals 
    WHERE referral_code IS NOT NULL 
    AND referral_code NOT IN (SELECT referral_code FROM sms_users WHERE referral_code IS NOT NULL);
    
    SELECT COUNT(*) INTO total_sms_users_after FROM sms_users;
    
    PERFORM log_cleanup_action('FINAL_CHECK', 'transcriptions', 'remaining_orphans', remaining_transcription_orphans);
    PERFORM log_cleanup_action('FINAL_CHECK', 'user_messages', 'remaining_orphans', remaining_message_orphans);
    PERFORM log_cleanup_action('FINAL_CHECK', 'credit_purchases', 'remaining_orphans', remaining_purchase_orphans);
    PERFORM log_cleanup_action('FINAL_CHECK', 'pending_referrals', 'remaining_orphans', remaining_referral_orphans);
    PERFORM log_cleanup_action('FINAL_CHECK', 'sms_users', 'total_after_cleanup', total_sms_users_after);
    
    RAISE NOTICE 'After cleanup:';
    RAISE NOTICE '  Total SMS users: %', total_sms_users_after;
    RAISE NOTICE '  Remaining transcription orphans: %', remaining_transcription_orphans;
    RAISE NOTICE '  Remaining message orphans: %', remaining_message_orphans;
    RAISE NOTICE '  Remaining purchase orphans: %', remaining_purchase_orphans;
    RAISE NOTICE '  Remaining referral orphans: %', remaining_referral_orphans;
    
    IF remaining_transcription_orphans = 0 AND remaining_message_orphans = 0 AND remaining_purchase_orphans = 0 THEN
        RAISE NOTICE '🎉 SUCCESS: All critical orphans resolved! Ready for FK constraints.';
        RAISE NOTICE 'Note: % referral orphans remain (will be handled separately)', remaining_referral_orphans;
    ELSE
        RAISE NOTICE '❌ ERROR: Critical orphans still exist - FK constraints will fail!';
        RAISE NOTICE 'Manual intervention required before proceeding.';
    END IF;
END $$;

-- ===========================================
-- 5. CLEANUP LOG SUMMARY
-- ===========================================

-- Show complete cleanup log
SELECT 
    step_name,
    table_name,
    action,
    record_count,
    details,
    timestamp
FROM cleanup_log 
ORDER BY timestamp;

-- Cleanup temporary objects
DROP FUNCTION log_cleanup_action(text, text, text, integer, text);

-- Success message
DO $$
BEGIN
    RAISE NOTICE '===========================================';
    RAISE NOTICE '📋 ORPHAN CLEANUP COMPLETED';
    RAISE NOTICE '===========================================';
    RAISE NOTICE 'Next step: Run the FK constraint migration';
    RAISE NOTICE 'File: 20250722000026_production_foreign_keys.sql';
    RAISE NOTICE '===========================================';
END $$;