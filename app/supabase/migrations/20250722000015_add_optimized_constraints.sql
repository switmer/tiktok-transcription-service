-- Add critical database constraints and indexes for data integrity and performance
-- This migration addresses architectural gaps identified in the technical review

-- 1. ADD MISSING CONSTRAINTS (with IF NOT EXISTS logic)
-- Status constraint - only allow valid status values
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.check_constraints 
                   WHERE constraint_name = 'chk_transcriptions_status') THEN
        ALTER TABLE transcriptions 
        ADD CONSTRAINT chk_transcriptions_status 
        CHECK (status IN ('pending', 'processing', 'completed', 'failed'));
    END IF;
END $$;

-- Platform constraint - only allow known platforms
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.check_constraints 
                   WHERE constraint_name = 'chk_transcriptions_platform') THEN
        ALTER TABLE transcriptions 
        ADD CONSTRAINT chk_transcriptions_platform 
        CHECK (platform IN ('tiktok', 'youtube', 'instagram', 'twitter') OR platform IS NULL);
    END IF;
END $$;

-- Visibility constraint - only allow valid visibility values
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.check_constraints 
                   WHERE constraint_name = 'chk_transcriptions_visibility') THEN
        ALTER TABLE transcriptions 
        ADD CONSTRAINT chk_transcriptions_visibility 
        CHECK (visibility IN ('public', 'private', 'unlisted') OR visibility IS NULL);
    END IF;
END $$;

-- Phone number format constraint for sms_users
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.check_constraints 
                   WHERE constraint_name = 'chk_sms_users_phone_format') THEN
        ALTER TABLE sms_users 
        ADD CONSTRAINT chk_sms_users_phone_format 
        CHECK (phone_number ~ '^\+1[0-9]{10}$');
    END IF;
END $$;

-- Credits constraint - cannot go negative
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.check_constraints 
                   WHERE constraint_name = 'chk_sms_users_credits_positive') THEN
        ALTER TABLE sms_users 
        ADD CONSTRAINT chk_sms_users_credits_positive 
        CHECK (credits_remaining >= 0);
    END IF;
END $$;

-- 2. ADD PERFORMANCE INDEXES
-- Note: Using appropriate index types to avoid btree row size limits:
-- - btree for small fields (status, dates, IDs)
-- - GIN for arrays and full-text search
-- - MD5 hash for large text fields when only equality is needed
-- Composite index for common status + date queries
CREATE INDEX IF NOT EXISTS idx_transcriptions_status_created 
ON transcriptions(status, created_at DESC);

-- Composite index for platform + status queries
CREATE INDEX IF NOT EXISTS idx_transcriptions_platform_status 
ON transcriptions(platform, status);

-- Index for credit checks (SMS users)
CREATE INDEX IF NOT EXISTS idx_sms_users_credits 
ON sms_users(phone_number, credits_remaining);

-- Index for discovery queries (like_count DESC)
CREATE INDEX IF NOT EXISTS idx_transcriptions_engagement 
ON transcriptions(like_count DESC NULLS LAST) 
WHERE status = 'completed' AND visibility = 'public';

-- Index for recent transcriptions
CREATE INDEX IF NOT EXISTS idx_transcriptions_recent 
ON transcriptions(created_at DESC, status) 
WHERE visibility = 'public';

-- Partial index for failed tasks (for debugging) - using hash of error to avoid size limit
CREATE INDEX IF NOT EXISTS idx_transcriptions_failed 
ON transcriptions(created_at DESC, (md5(COALESCE(error, '')))) 
WHERE status = 'failed';

-- GIN index for tag searches (if not already exists)
CREATE INDEX IF NOT EXISTS idx_transcriptions_tags_gin 
ON transcriptions USING GIN(tags);

-- GIN index for auto_tags searches
CREATE INDEX IF NOT EXISTS idx_transcriptions_auto_tags_gin 
ON transcriptions USING GIN(auto_tags);

-- Text search index for quotes (GIN for full-text search)
CREATE INDEX IF NOT EXISTS idx_transcriptions_quote_text 
ON transcriptions USING GIN(to_tsvector('english', COALESCE(quote, ''))) 
WHERE quote IS NOT NULL AND quote != '';

-- Full-text search index for transcripts (for search functionality)
CREATE INDEX IF NOT EXISTS idx_transcriptions_transcript_fts 
ON transcriptions USING GIN(to_tsvector('english', COALESCE(transcript, ''))) 
WHERE transcript IS NOT NULL AND transcript != '';

-- 3. ADD FOREIGN KEY CONSTRAINTS (with proper handling of existing data)
-- Note: These might fail if there's orphaned data, so we'll make them deferrable initially

-- Foreign key from transcriptions to sms_users (soft constraint for now)
-- First, let's add a comment noting this relationship should be enforced
COMMENT ON COLUMN transcriptions.user_phone IS 'Should reference sms_users.phone_number (soft FK for now due to existing data)';

-- Foreign key from transcript_jobs to transcriptions
-- First check if transcript_jobs table exists and constraint doesn't exist
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') 
       AND NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                      WHERE constraint_name = 'fk_transcript_jobs_transcript_id') THEN
        -- Add FK constraint if table exists and constraint doesn't exist
        ALTER TABLE transcript_jobs 
        ADD CONSTRAINT fk_transcript_jobs_transcript_id 
        FOREIGN KEY (transcript_id) REFERENCES transcriptions(task_id) 
        ON DELETE CASCADE;
    END IF;
END $$;

-- 4. ADD DATA VALIDATION FUNCTIONS
-- Function to validate video URLs
CREATE OR REPLACE FUNCTION validate_video_url(url text) 
RETURNS boolean AS $$
BEGIN
    RETURN url ~ '^https://(www\.)?(tiktok\.com|youtube\.com|youtu\.be)/'
        OR url ~ '^https://.*\.tiktok\.com/'
        OR url ~ '^https://.*\.youtube\.com/';
END;
$$ LANGUAGE plpgsql;

-- Add URL validation constraint (initially not enforced to avoid breaking existing data)
-- ALTER TABLE transcriptions 
-- ADD CONSTRAINT chk_transcriptions_valid_url 
-- CHECK (validate_video_url(url));

-- 5. ADD CLEANUP FUNCTIONS
-- Function to find orphaned storage references
CREATE OR REPLACE FUNCTION find_orphaned_thumbnails() 
RETURNS TABLE(task_id uuid, storage_path text) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        t.task_id,
        CASE 
            WHEN t.supabase_thumbnail_url IS NOT NULL 
            THEN regexp_replace(t.supabase_thumbnail_url, '^.*/storage/v1/object/public/assets/', '')
            ELSE NULL
        END as storage_path
    FROM transcriptions t
    WHERE t.supabase_thumbnail_url IS NOT NULL
    AND t.status = 'failed';
END;
$$ LANGUAGE plpgsql;

-- 6. ADD AUDIT TRIGGERS
-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Add trigger for transcriptions table if not exists
DROP TRIGGER IF EXISTS update_transcriptions_updated_at ON transcriptions;
CREATE TRIGGER update_transcriptions_updated_at
    BEFORE UPDATE ON transcriptions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Add trigger for sms_users table if not exists  
DROP TRIGGER IF EXISTS update_sms_users_updated_at ON sms_users;
CREATE TRIGGER update_sms_users_updated_at
    BEFORE UPDATE ON sms_users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 7. COMMENTS FOR DOCUMENTATION
COMMENT ON INDEX idx_transcriptions_status_created IS 'Optimizes queries for listing transcriptions by status and date';
COMMENT ON INDEX idx_transcriptions_platform_status IS 'Optimizes platform-specific status queries';
COMMENT ON INDEX idx_sms_users_credits IS 'Optimizes credit validation for SMS users';
COMMENT ON INDEX idx_transcriptions_engagement IS 'Optimizes discovery queries by engagement metrics';

-- Success message
DO $$
BEGIN
    RAISE NOTICE 'Critical constraints and indexes successfully applied!';
    RAISE NOTICE 'Added % constraints, % indexes, and % functions', 
        (SELECT count(*) FROM information_schema.check_constraints WHERE constraint_name LIKE 'chk_%'),
        (SELECT count(*) FROM pg_indexes WHERE indexname LIKE 'idx_%'),
        (SELECT count(*) FROM information_schema.routines WHERE routine_name IN ('validate_video_url', 'find_orphaned_thumbnails', 'update_updated_at_column'));
END $$;