-- PRODUCTION-GRADE FOREIGN KEY CONSTRAINTS
-- Step 2: Add FK constraints with proper CASCADE policies for SaaS production environment
-- Run AFTER orphan cleanup migration (20250722000025)

-- ===========================================
-- 1. PRE-FLIGHT SAFETY CHECKS
-- ===========================================

DO $$
DECLARE
    orphan_count integer;
    constraint_exists boolean;
BEGIN
    RAISE NOTICE '=== PRE-FLIGHT SAFETY CHECKS ===';
    
    -- Final orphan verification
    SELECT COUNT(*) INTO orphan_count FROM (
        SELECT user_phone FROM transcriptions 
        WHERE user_phone IS NOT NULL 
        AND user_phone NOT IN (SELECT phone_number FROM sms_users WHERE phone_number IS NOT NULL)
        
        UNION ALL
        
        SELECT from_phone FROM user_messages 
        WHERE from_phone IS NOT NULL 
        AND from_phone NOT IN (SELECT phone_number FROM sms_users WHERE phone_number IS NOT NULL)
        
        UNION ALL
        
        SELECT phone_number FROM credit_purchases 
        WHERE phone_number IS NOT NULL 
        AND phone_number NOT IN (SELECT phone_number FROM sms_users WHERE phone_number IS NOT NULL)
    ) all_remaining_orphans;
    
    IF orphan_count > 0 THEN
        RAISE EXCEPTION 'SAFETY CHECK FAILED: % orphaned records still exist. Run orphan cleanup first!', orphan_count;
    ELSE
        RAISE NOTICE '✅ Safety check passed: No orphaned records found';
    END IF;
    
    -- Check if any constraints already exist
    SELECT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name LIKE 'fk_%' 
        AND table_name IN ('transcriptions', 'user_messages', 'credit_purchases')
        AND constraint_type = 'FOREIGN KEY'
    ) INTO constraint_exists;
    
    IF constraint_exists THEN
        RAISE NOTICE '⚠️ Some FK constraints already exist - will skip existing ones';
    ELSE
        RAISE NOTICE '✅ No existing FK constraints found - will add all new constraints';
    END IF;
END $$;

-- ===========================================
-- 2. ADD FOREIGN KEY CONSTRAINTS WITH PRODUCTION POLICIES
-- ===========================================

-- FK 1: transcriptions.user_phone → sms_users.phone_number
-- Policy: SET NULL (preserve transcription data even if user is deleted)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_transcriptions_user_phone') THEN
        
        ALTER TABLE transcriptions 
        ADD CONSTRAINT fk_transcriptions_user_phone 
        FOREIGN KEY (user_phone) REFERENCES sms_users(phone_number) 
        ON DELETE SET NULL      -- Preserve transcriptions for analytics
        ON UPDATE CASCADE;      -- Update phone if user changes number
        
        RAISE NOTICE '✅ Added: transcriptions.user_phone → sms_users.phone_number (SET NULL)';
    ELSE
        RAISE NOTICE '⏭️ Skipped: transcriptions.user_phone FK already exists';
    END IF;
END $$;

-- FK 2: user_messages.from_phone → sms_users.phone_number
-- Policy: CASCADE (if user is deleted, delete their message history)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_user_messages_from_phone') THEN
        
        ALTER TABLE user_messages 
        ADD CONSTRAINT fk_user_messages_from_phone 
        FOREIGN KEY (from_phone) REFERENCES sms_users(phone_number) 
        ON DELETE CASCADE       -- Delete messages if user is deleted
        ON UPDATE CASCADE;      -- Update phone if user changes number
        
        RAISE NOTICE '✅ Added: user_messages.from_phone → sms_users.phone_number (CASCADE)';
    ELSE
        RAISE NOTICE '⏭️ Skipped: user_messages.from_phone FK already exists';
    END IF;
END $$;

-- FK 3: credit_purchases.phone_number → sms_users.phone_number
-- Policy: RESTRICT (prevent deleting users who have purchase history)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_name = 'fk_credit_purchases_phone_number') THEN
        
        ALTER TABLE credit_purchases 
        ADD CONSTRAINT fk_credit_purchases_phone_number 
        FOREIGN KEY (phone_number) REFERENCES sms_users(phone_number) 
        ON DELETE RESTRICT      -- Prevent deletion if user has purchases
        ON UPDATE CASCADE;      -- Update phone if user changes number
        
        RAISE NOTICE '✅ Added: credit_purchases.phone_number → sms_users.phone_number (RESTRICT)';
    ELSE
        RAISE NOTICE '⏭️ Skipped: credit_purchases.phone_number FK already exists';
    END IF;
END $$;

-- FK 4: pending_referrals.referral_code → sms_users.referral_code (OPTIONAL)
-- Policy: CASCADE (delete pending referrals if referrer is deleted)
DO $$
DECLARE
    orphan_referral_count integer;
BEGIN
    -- Check for orphaned referral codes first
    SELECT COUNT(*) INTO orphan_referral_count
    FROM pending_referrals 
    WHERE referral_code IS NOT NULL 
    AND referral_code NOT IN (SELECT referral_code FROM sms_users WHERE referral_code IS NOT NULL);
    
    IF orphan_referral_count = 0 THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                       WHERE constraint_name = 'fk_pending_referrals_code') THEN
            
            ALTER TABLE pending_referrals 
            ADD CONSTRAINT fk_pending_referrals_code 
            FOREIGN KEY (referral_code) REFERENCES sms_users(referral_code) 
            ON DELETE CASCADE       -- Delete pending referrals if referrer is deleted
            ON UPDATE CASCADE;      -- Update code if referrer changes code
            
            RAISE NOTICE '✅ Added: pending_referrals.referral_code → sms_users.referral_code (CASCADE)';
        ELSE
            RAISE NOTICE '⏭️ Skipped: pending_referrals.referral_code FK already exists';
        END IF;
    ELSE
        RAISE NOTICE '⚠️ Skipped: pending_referrals.referral_code FK (% orphaned codes)', orphan_referral_count;
        RAISE NOTICE '   Run: DELETE FROM pending_referrals WHERE referral_code NOT IN (SELECT referral_code FROM sms_users)';
    END IF;
END $$;

-- ===========================================
-- 3. ADD PERFORMANCE INDEXES FOR FK COLUMNS
-- ===========================================

-- Index for transcriptions.user_phone FK lookups
CREATE INDEX IF NOT EXISTS idx_transcriptions_user_phone_fk 
ON transcriptions(user_phone) 
WHERE user_phone IS NOT NULL;

-- Index for user_messages.from_phone FK lookups
CREATE INDEX IF NOT EXISTS idx_user_messages_from_phone_fk 
ON user_messages(from_phone);

-- Index for credit_purchases.phone_number FK lookups
CREATE INDEX IF NOT EXISTS idx_credit_purchases_phone_number_fk 
ON credit_purchases(phone_number);

-- Index for pending_referrals.referral_code FK lookups
CREATE INDEX IF NOT EXISTS idx_pending_referrals_code_fk 
ON pending_referrals(referral_code) 
WHERE referral_code IS NOT NULL;

-- Composite index for common user analytics queries
CREATE INDEX IF NOT EXISTS idx_transcriptions_user_analytics 
ON transcriptions(user_phone, status, created_at DESC) 
WHERE user_phone IS NOT NULL AND status = 'completed';

-- Composite index for user engagement tracking
CREATE INDEX IF NOT EXISTS idx_user_messages_engagement 
ON user_messages(from_phone, created_at DESC, command);

DO $$
BEGIN
    RAISE NOTICE '✅ Added performance indexes for all FK relationships';
END $$;

-- ===========================================
-- 4. ADD CONSTRAINT DOCUMENTATION
-- ===========================================

-- Document FK behavior for future developers
COMMENT ON CONSTRAINT fk_transcriptions_user_phone ON transcriptions IS 
'Links transcriptions to SMS users. ON DELETE SET NULL preserves transcription data for analytics even if user is deleted.';

COMMENT ON CONSTRAINT fk_user_messages_from_phone ON user_messages IS 
'Links messages to SMS users. ON DELETE CASCADE removes message history when user is deleted.';

COMMENT ON CONSTRAINT fk_credit_purchases_phone_number ON credit_purchases IS 
'Links purchases to SMS users. ON DELETE RESTRICT prevents user deletion if they have purchase history.';

-- Add table-level comments
COMMENT ON TABLE transcriptions IS 'Video transcription records with optional user association for analytics';
COMMENT ON TABLE user_messages IS 'SMS message history tied to user accounts';
COMMENT ON TABLE credit_purchases IS 'Credit purchase records with strict user referential integrity';

DO $$
BEGIN
    RAISE NOTICE '✅ Added comprehensive constraint documentation';
END $$;

-- ===========================================
-- 5. VALIDATION FUNCTIONS FOR ONGOING INTEGRITY
-- ===========================================

-- Function to check FK integrity health
CREATE OR REPLACE FUNCTION check_fk_integrity() 
RETURNS TABLE(
    table_name text,
    fk_column text,
    orphan_count bigint,
    total_records bigint,
    integrity_percent numeric
) AS $$
BEGIN
    -- Check transcriptions FK integrity
    RETURN QUERY
    SELECT 
        'transcriptions'::text,
        'user_phone'::text,
        COUNT(*) FILTER (WHERE t.user_phone IS NOT NULL AND s.phone_number IS NULL) as orphan_count,
        COUNT(*) as total_records,
        ROUND(
            (COUNT(*) FILTER (WHERE t.user_phone IS NULL OR s.phone_number IS NOT NULL) * 100.0) / 
            NULLIF(COUNT(*), 0), 2
        ) as integrity_percent
    FROM transcriptions t
    LEFT JOIN sms_users s ON t.user_phone = s.phone_number;
    
    -- Check user_messages FK integrity
    RETURN QUERY
    SELECT 
        'user_messages'::text,
        'from_phone'::text,
        COUNT(*) FILTER (WHERE m.from_phone IS NOT NULL AND s.phone_number IS NULL) as orphan_count,
        COUNT(*) as total_records,
        ROUND(
            (COUNT(*) FILTER (WHERE s.phone_number IS NOT NULL) * 100.0) / 
            NULLIF(COUNT(*), 0), 2
        ) as integrity_percent
    FROM user_messages m
    LEFT JOIN sms_users s ON m.from_phone = s.phone_number;
    
    -- Check credit_purchases FK integrity
    RETURN QUERY
    SELECT 
        'credit_purchases'::text,
        'phone_number'::text,
        COUNT(*) FILTER (WHERE cp.phone_number IS NOT NULL AND s.phone_number IS NULL) as orphan_count,
        COUNT(*) as total_records,
        ROUND(
            (COUNT(*) FILTER (WHERE s.phone_number IS NOT NULL) * 100.0) / 
            NULLIF(COUNT(*), 0), 2
        ) as integrity_percent
    FROM credit_purchases cp
    LEFT JOIN sms_users s ON cp.phone_number = s.phone_number;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION check_fk_integrity() IS 
'Health check function to monitor foreign key integrity across all user-related tables';

-- Function to safely clean up orphaned referral codes
CREATE OR REPLACE FUNCTION cleanup_orphaned_referrals() 
RETURNS integer AS $$
DECLARE
    deleted_count integer;
BEGIN
    DELETE FROM pending_referrals 
    WHERE referral_code IS NOT NULL 
    AND referral_code NOT IN (
        SELECT referral_code FROM sms_users 
        WHERE referral_code IS NOT NULL
    );
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_orphaned_referrals() IS 
'Safely removes pending referrals with invalid referral codes';

DO $$
BEGIN
    RAISE NOTICE '✅ Added integrity monitoring and cleanup functions';
END $$;

-- ===========================================
-- 6. FINAL VALIDATION AND SUMMARY
-- ===========================================

DO $$
DECLARE
    fk_count integer;
    index_count integer;
    integrity_results record;
    total_sms_users integer;
    total_transcriptions integer;
    total_messages integer;
    total_purchases integer;
BEGIN
    RAISE NOTICE '=== FINAL VALIDATION AND SUMMARY ===';
    
    -- Count added constraints
    SELECT COUNT(*) INTO fk_count
    FROM information_schema.table_constraints 
    WHERE constraint_type = 'FOREIGN KEY'
    AND constraint_name IN (
        'fk_transcriptions_user_phone',
        'fk_user_messages_from_phone', 
        'fk_credit_purchases_phone_number',
        'fk_pending_referrals_code'
    );
    
    -- Count added indexes
    SELECT COUNT(*) INTO index_count
    FROM pg_indexes 
    WHERE indexname LIKE 'idx_%_fk' 
    AND tablename IN ('transcriptions', 'user_messages', 'credit_purchases', 'pending_referrals');
    
    -- Get table counts
    SELECT COUNT(*) INTO total_sms_users FROM sms_users;
    SELECT COUNT(*) INTO total_transcriptions FROM transcriptions;
    SELECT COUNT(*) INTO total_messages FROM user_messages;
    SELECT COUNT(*) INTO total_purchases FROM credit_purchases;
    
    RAISE NOTICE '';
    RAISE NOTICE '🎉 FOREIGN KEY MIGRATION COMPLETED SUCCESSFULLY!';
    RAISE NOTICE '';
    RAISE NOTICE '📊 SUMMARY:';
    RAISE NOTICE '  Foreign key constraints added: %', fk_count;
    RAISE NOTICE '  Performance indexes added: %', index_count;
    RAISE NOTICE '  Total SMS users: %', total_sms_users;
    RAISE NOTICE '  Total transcriptions: %', total_transcriptions;
    RAISE NOTICE '  Total user messages: %', total_messages;
    RAISE NOTICE '  Total credit purchases: %', total_purchases;
    RAISE NOTICE '';
    RAISE NOTICE '🔐 CASCADE POLICIES:';
    RAISE NOTICE '  transcriptions.user_phone: SET NULL (preserves analytics)';
    RAISE NOTICE '  user_messages.from_phone: CASCADE (removes message history)';
    RAISE NOTICE '  credit_purchases.phone_number: RESTRICT (protects purchase history)';
    RAISE NOTICE '  pending_referrals.referral_code: CASCADE (cleans up referrals)';
    RAISE NOTICE '';
    RAISE NOTICE '🔍 MONITORING:';
    RAISE NOTICE '  Run: SELECT * FROM check_fk_integrity();';
    RAISE NOTICE '  Run: SELECT cleanup_orphaned_referrals();';
    RAISE NOTICE '';
    RAISE NOTICE '✅ Your database now has enterprise-grade referential integrity!';
    RAISE NOTICE '✅ Ready for analytics, user management, and credit operations!';
    RAISE NOTICE '✅ Next: Regenerate TypeScript types and update documentation!';
END $$;

-- Test the integrity check function
SELECT 
    table_name,
    fk_column,
    orphan_count,
    total_records,
    integrity_percent || '%' as integrity
FROM check_fk_integrity();

-- Success banner
DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '==========================================';
    RAISE NOTICE '🚀 PRODUCTION FK CONSTRAINTS COMPLETE! 🚀';
    RAISE NOTICE '==========================================';
END $$;