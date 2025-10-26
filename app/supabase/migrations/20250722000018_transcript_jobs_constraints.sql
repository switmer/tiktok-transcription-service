-- Add comprehensive constraints and indexes for transcript_jobs table
-- This ensures robust job tracking and SMS queue management

-- Only proceed if transcript_jobs table exists
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        RAISE NOTICE 'transcript_jobs table does not exist - skipping constraints';
        RETURN;
    END IF;

    RAISE NOTICE 'Adding constraints and indexes to transcript_jobs table...';
END $$;

-- 1. ADD CHECK CONSTRAINTS for valid data

-- Status constraint - only allow valid job statuses
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') 
       AND NOT EXISTS (SELECT 1 FROM information_schema.check_constraints 
                       WHERE constraint_name = 'chk_transcript_jobs_status') THEN
        ALTER TABLE transcript_jobs 
        ADD CONSTRAINT chk_transcript_jobs_status 
        CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled'));
    END IF;
END $$;

-- Phone number format constraint (consistent with sms_users)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') 
       AND NOT EXISTS (SELECT 1 FROM information_schema.check_constraints 
                       WHERE constraint_name = 'chk_transcript_jobs_phone_format') THEN
        ALTER TABLE transcript_jobs 
        ADD CONSTRAINT chk_transcript_jobs_phone_format 
        CHECK (from_phone ~ '^\\+1[0-9]{10}$' AND to_phone ~ '^\\+1[0-9]{10}$');
    END IF;
END $$;

-- URL validation constraint
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') 
       AND NOT EXISTS (SELECT 1 FROM information_schema.check_constraints 
                       WHERE constraint_name = 'chk_transcript_jobs_url_format') THEN
        ALTER TABLE transcript_jobs 
        ADD CONSTRAINT chk_transcript_jobs_url_format 
        CHECK (video_url ~ '^https://(www\\.)?(tiktok\\.com|youtube\\.com|youtu\\.be)/');
    END IF;
END $$;

-- 2. ADD NOT NULL CONSTRAINTS for required fields
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        -- Make core fields NOT NULL if they aren't already
        BEGIN
            ALTER TABLE transcript_jobs ALTER COLUMN from_phone SET NOT NULL;
        EXCEPTION WHEN others THEN
            -- Column might already be NOT NULL or have other constraints
            NULL;
        END;
        
        BEGIN
            ALTER TABLE transcript_jobs ALTER COLUMN video_url SET NOT NULL;
        EXCEPTION WHEN others THEN
            NULL;
        END;
        
        BEGIN
            ALTER TABLE transcript_jobs ALTER COLUMN status SET NOT NULL;
        EXCEPTION WHEN others THEN
            NULL;
        END;
    END IF;
END $$;

-- 3. ADD DEFAULT VALUES for better data consistency
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        -- Set default status to 'pending'
        BEGIN
            ALTER TABLE transcript_jobs ALTER COLUMN status SET DEFAULT 'pending';
        EXCEPTION WHEN others THEN
            NULL;
        END;
        
        -- Set default created_at to now()
        BEGIN
            ALTER TABLE transcript_jobs ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;
        EXCEPTION WHEN others THEN
            NULL;
        END;
        
        -- Set default updated_at to now()
        BEGIN
            ALTER TABLE transcript_jobs ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP;
        EXCEPTION WHEN others THEN
            NULL;
        END;
    END IF;
END $$;

-- 4. ADD PERFORMANCE INDEXES for common query patterns

-- Index for user's job history (most common query)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_transcript_jobs_user_history 
                ON transcript_jobs(from_phone, created_at DESC, status)';
    END IF;
END $$;

-- Index for processing queue (jobs to be processed)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_transcript_jobs_processing_queue 
                ON transcript_jobs(status, created_at ASC) 
                WHERE status IN (''pending'', ''processing'')';
    END IF;
END $$;

-- Index for error tracking and debugging
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_transcript_jobs_errors 
                ON transcript_jobs(status, updated_at DESC) 
                WHERE status = ''failed'' AND error_message IS NOT NULL';
    END IF;
END $$;

-- Index for completion tracking
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_transcript_jobs_completed 
                ON transcript_jobs(transcript_id, status, updated_at DESC) 
                WHERE status = ''completed''';
    END IF;
END $$;

-- Composite index for admin/monitoring queries
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_transcript_jobs_monitoring 
                ON transcript_jobs(status, created_at DESC, from_phone)';
    END IF;
END $$;

-- 5. ADD TRIGGER for automatic updated_at timestamp
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        -- Create trigger if it doesn't exist
        IF NOT EXISTS (SELECT 1 FROM information_schema.triggers 
                       WHERE trigger_name = 'update_transcript_jobs_updated_at') THEN
            EXECUTE 'CREATE TRIGGER update_transcript_jobs_updated_at
                    BEFORE UPDATE ON transcript_jobs
                    FOR EACH ROW
                    EXECUTE FUNCTION update_updated_at_column()';
        END IF;
    END IF;
END $$;

-- 6. ADD UNIQUE CONSTRAINTS to prevent duplicate jobs

-- Prevent duplicate pending jobs for same user+URL
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') 
       AND NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                       WHERE constraint_name = 'uq_transcript_jobs_pending_unique') THEN
        EXECUTE 'CREATE UNIQUE INDEX uq_transcript_jobs_pending_unique 
                ON transcript_jobs(from_phone, video_url) 
                WHERE status IN (''pending'', ''processing'')';
    END IF;
END $$;

-- 7. ADD HELPER FUNCTIONS for job management

-- Function to get job queue depth for monitoring
CREATE OR REPLACE FUNCTION get_job_queue_depth() 
RETURNS TABLE(status text, count bigint) AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        RETURN QUERY
        SELECT tj.status, COUNT(*)
        FROM transcript_jobs tj
        WHERE tj.status IN ('pending', 'processing', 'failed')
        GROUP BY tj.status
        ORDER BY tj.status;
    ELSE
        -- Return empty result if table doesn't exist
        RETURN;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function to get user's job statistics
CREATE OR REPLACE FUNCTION get_user_job_stats(user_phone_param text) 
RETURNS TABLE(
    total_jobs bigint,
    completed_jobs bigint,
    failed_jobs bigint,
    pending_jobs bigint,
    success_rate numeric
) AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        RETURN QUERY
        SELECT 
            COUNT(*) as total_jobs,
            COUNT(*) FILTER (WHERE status = 'completed') as completed_jobs,
            COUNT(*) FILTER (WHERE status = 'failed') as failed_jobs,
            COUNT(*) FILTER (WHERE status IN ('pending', 'processing')) as pending_jobs,
            CASE 
                WHEN COUNT(*) > 0 THEN 
                    ROUND(COUNT(*) FILTER (WHERE status = 'completed') * 100.0 / COUNT(*), 2)
                ELSE 0 
            END as success_rate
        FROM transcript_jobs 
        WHERE from_phone = user_phone_param;
    ELSE
        -- Return zeros if table doesn't exist
        RETURN QUERY SELECT 0::bigint, 0::bigint, 0::bigint, 0::bigint, 0::numeric;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function to clean up old completed jobs (for maintenance)
CREATE OR REPLACE FUNCTION cleanup_old_transcript_jobs(days_old integer DEFAULT 30) 
RETURNS bigint AS $$
DECLARE
    deleted_count bigint := 0;
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        DELETE FROM transcript_jobs 
        WHERE status = 'completed' 
        AND created_at < (CURRENT_TIMESTAMP - INTERVAL '1 day' * days_old);
        
        GET DIAGNOSTICS deleted_count = ROW_COUNT;
    END IF;
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- 8. ADD COMMENTS for documentation
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        EXECUTE 'COMMENT ON TABLE transcript_jobs IS ''SMS job queue for transcription requests''';
        EXECUTE 'COMMENT ON CONSTRAINT chk_transcript_jobs_status ON transcript_jobs IS ''Ensures only valid job statuses''';
        EXECUTE 'COMMENT ON INDEX idx_transcript_jobs_user_history IS ''Optimizes user job history queries''';
        EXECUTE 'COMMENT ON INDEX idx_transcript_jobs_processing_queue IS ''Optimizes job queue processing''';
        EXECUTE 'COMMENT ON INDEX uq_transcript_jobs_pending_unique IS ''Prevents duplicate pending jobs for same user+URL''';
    END IF;
END $$;

-- Success message
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'transcript_jobs') THEN
        RAISE NOTICE 'transcript_jobs constraints and indexes successfully added!';
        RAISE NOTICE 'Added: status checks, phone format validation, performance indexes';
        RAISE NOTICE 'Added: duplicate prevention, auto-timestamps, helper functions';
        RAISE NOTICE 'Added: monitoring functions for queue depth and user stats';
    ELSE
        RAISE NOTICE 'transcript_jobs table not found - migration skipped';
    END IF;
END $$;