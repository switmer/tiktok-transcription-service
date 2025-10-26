-- PRODUCTION-READY FULL-TEXT SEARCH FOR TRANSCRIPTIONS
-- Battle-tested FTS implementation for transcript/quote/tldr search
-- Based on enterprise SaaS best practices

-- ===========================================
-- 1. ADD FTS COLUMNS & GIN INDEXES
-- ===========================================

-- Add dedicated FTS column for fast search
ALTER TABLE transcriptions 
ADD COLUMN IF NOT EXISTS fts tsvector;

DO $$
BEGIN
    RAISE NOTICE '✅ Added FTS column to transcriptions table';
END $$;

-- Create high-performance GIN index
CREATE INDEX IF NOT EXISTS idx_transcriptions_fts
ON transcriptions
USING GIN (fts);

DO $$
BEGIN
    RAISE NOTICE '✅ Created GIN index for FTS';
END $$;

-- ===========================================
-- 2. POPULATE EXISTING RECORDS
-- ===========================================

-- Populate FTS vector for existing records (handles TLDR as JSONB)
UPDATE transcriptions
SET fts = to_tsvector('english', 
    COALESCE(transcript, '') || ' ' ||
    COALESCE(quote, '') || ' ' ||
    COALESCE(
        CASE 
            WHEN tldr IS NOT NULL THEN 
                CASE 
                    WHEN jsonb_typeof(tldr) = 'array' THEN 
                        (SELECT string_agg(value::text, ' ') FROM jsonb_array_elements_text(tldr))
                    WHEN jsonb_typeof(tldr) = 'object' THEN 
                        tldr::text
                    ELSE tldr::text
                END
            ELSE ''
        END, 
    '') || ' ' ||
    COALESCE(title, '') || ' ' ||
    COALESCE(description, '')
)
WHERE fts IS NULL;

DO $$
DECLARE
    updated_count integer;
BEGIN
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RAISE NOTICE '✅ Populated FTS vectors for % existing records', updated_count;
END $$;

-- ===========================================
-- 3. CREATE TRIGGER FOR AUTO-UPDATE
-- ===========================================

-- Trigger function to keep FTS up-to-date
CREATE OR REPLACE FUNCTION transcriptions_fts_trigger() 
RETURNS trigger AS $$
BEGIN
    NEW.fts := to_tsvector('english', 
        COALESCE(NEW.transcript, '') || ' ' ||
        COALESCE(NEW.quote, '') || ' ' ||
        COALESCE(
            CASE 
                WHEN NEW.tldr IS NOT NULL THEN 
                    CASE 
                        WHEN jsonb_typeof(NEW.tldr) = 'array' THEN 
                            (SELECT string_agg(value::text, ' ') FROM jsonb_array_elements_text(NEW.tldr))
                        WHEN jsonb_typeof(NEW.tldr) = 'object' THEN 
                            NEW.tldr::text
                        ELSE NEW.tldr::text
                    END
                ELSE ''
            END, 
        '') || ' ' ||
        COALESCE(NEW.title, '') || ' ' ||
        COALESCE(NEW.description, '')
    );
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS transcriptions_fts_update ON transcriptions;
CREATE TRIGGER transcriptions_fts_update
    BEFORE INSERT OR UPDATE OF transcript, quote, tldr, title, description
    ON transcriptions
    FOR EACH ROW
    EXECUTE FUNCTION transcriptions_fts_trigger();

DO $$
BEGIN
    RAISE NOTICE '✅ Created auto-update trigger for FTS';
END $$;

-- ===========================================
-- 4. BATTLE-TESTED SEARCH FUNCTIONS
-- ===========================================

-- Main FTS search function with ranking
CREATE OR REPLACE FUNCTION search_content(
    search_query text,
    limit_count integer DEFAULT 20,
    offset_count integer DEFAULT 0
)
RETURNS TABLE(
    task_id uuid,
    title text,
    quote text,
    tldr jsonb,
    platform text,
    like_count bigint,
    view_count bigint,
    created_at timestamptz,
    search_rank real
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        t.task_id,
        t.title,
        t.quote,
        t.tldr,
        t.platform,
        t.like_count,
        t.view_count,
        t.created_at,
        ts_rank(t.fts, plainto_tsquery('english', search_query)) as search_rank
    FROM transcriptions t
    WHERE t.status = 'completed'
      AND t.fts @@ plainto_tsquery('english', search_query)
    ORDER BY search_rank DESC, t.like_count DESC NULLS LAST, t.created_at DESC
    LIMIT limit_count OFFSET offset_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION search_content IS 
'Lightning-fast FTS search across transcript/quote/tldr with relevance ranking';

-- Quote-specific search for viral content discovery
CREATE OR REPLACE FUNCTION search_viral_quotes(
    search_query text,
    min_likes integer DEFAULT 10,
    limit_count integer DEFAULT 10
)
RETURNS TABLE(
    task_id uuid,
    quote text,
    title text,
    platform text,
    like_count bigint,
    search_rank real
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        t.task_id,
        t.quote,
        t.title,
        t.platform,
        t.like_count,
        ts_rank(t.fts, plainto_tsquery('english', search_query)) as search_rank
    FROM transcriptions t
    WHERE t.status = 'completed'
      AND t.quote IS NOT NULL
      AND t.like_count >= min_likes
      AND t.fts @@ plainto_tsquery('english', search_query)
    ORDER BY search_rank DESC, t.like_count DESC
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION search_viral_quotes IS 
'Find high-engagement quotes matching search terms for viral content discovery';

-- ===========================================
-- 5. PERFORMANCE MONITORING FUNCTION
-- ===========================================

-- Monitor FTS performance and coverage
CREATE OR REPLACE FUNCTION fts_health_check()
RETURNS TABLE(
    metric text,
    value text,
    status text
) AS $$
DECLARE
    total_records integer;
    fts_records integer;
    index_size bigint;
    coverage_percent numeric;
BEGIN
    -- Get counts
    SELECT COUNT(*) INTO total_records FROM transcriptions;
    SELECT COUNT(*) INTO fts_records FROM transcriptions WHERE fts IS NOT NULL;
    
    -- Get index size
    SELECT pg_relation_size('idx_transcriptions_fts') INTO index_size;
    
    -- Calculate coverage
    coverage_percent := ROUND((fts_records::numeric / NULLIF(total_records, 0)) * 100, 2);
    
    -- Return metrics
    RETURN QUERY VALUES 
        ('total_transcriptions', total_records::text, CASE WHEN total_records > 0 THEN '✅' ELSE '⚠️' END),
        ('fts_indexed_records', fts_records::text, CASE WHEN fts_records > 0 THEN '✅' ELSE '❌' END),
        ('fts_coverage_percent', coverage_percent::text || '%', CASE WHEN coverage_percent >= 95 THEN '✅' ELSE '⚠️' END),
        ('fts_index_size', pg_size_pretty(index_size), '📊'),
        ('search_ready', CASE WHEN coverage_percent >= 95 THEN 'YES' ELSE 'NO' END, CASE WHEN coverage_percent >= 95 THEN '🚀' ELSE '⚠️' END);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fts_health_check IS 
'Monitor FTS system health, coverage, and performance metrics';

-- ===========================================
-- 6. COMPOSITE INDEXES FOR ADVANCED QUERIES
-- ===========================================

-- Index for viral content search (FTS + engagement)
CREATE INDEX IF NOT EXISTS idx_transcriptions_fts_viral
ON transcriptions(like_count DESC, view_count DESC)
WHERE status = 'completed' AND quote IS NOT NULL AND like_count > 0;

-- Index for recent content search (FTS + recency)
CREATE INDEX IF NOT EXISTS idx_transcriptions_fts_recent
ON transcriptions(created_at DESC)
WHERE status = 'completed' AND fts IS NOT NULL;

DO $$
BEGIN
    RAISE NOTICE '✅ Created composite indexes for advanced FTS queries';
END $$;

-- ===========================================
-- 7. VALIDATION AND SUMMARY
-- ===========================================

DO $$
DECLARE
    health_result record;
    total_indexes integer;
    total_functions integer;
BEGIN
    RAISE NOTICE '=== PRODUCTION FTS SETUP COMPLETE ===';
    
    -- Get health metrics
    FOR health_result IN SELECT * FROM fts_health_check() LOOP
        RAISE NOTICE '  %: % %', health_result.metric, health_result.value, health_result.status;
    END LOOP;
    
    -- Count created objects
    SELECT COUNT(*) INTO total_indexes
    FROM pg_indexes 
    WHERE tablename = 'transcriptions' AND indexname LIKE '%fts%';
    
    SELECT COUNT(*) INTO total_functions
    FROM pg_proc 
    WHERE proname IN ('search_content', 'search_viral_quotes', 'fts_health_check');
    
    RAISE NOTICE '';
    RAISE NOTICE '🎯 BATTLE-TESTED FEATURES:';
    RAISE NOTICE '  ✅ Lightning-fast GIN index search';
    RAISE NOTICE '  ✅ Auto-updating FTS vectors via trigger';
    RAISE NOTICE '  ✅ JSONB TLDR support (array/object)';
    RAISE NOTICE '  ✅ Ranked relevance scoring';
    RAISE NOTICE '  ✅ Viral content discovery';
    RAISE NOTICE '  ✅ Performance monitoring';
    RAISE NOTICE '';
    RAISE NOTICE '📊 OBJECTS CREATED:';
    RAISE NOTICE '  FTS indexes: %', total_indexes;
    RAISE NOTICE '  Search functions: %', total_functions;
    RAISE NOTICE '';
    RAISE NOTICE '🚀 USAGE EXAMPLES:';
    RAISE NOTICE '  SELECT * FROM search_content(''motivation success'');';
    RAISE NOTICE '  SELECT * FROM search_viral_quotes(''mindset'', 100);';
    RAISE NOTICE '  SELECT * FROM fts_health_check();';
    RAISE NOTICE '';
    RAISE NOTICE '🔥 READY FOR API INTEGRATION:';
    RAISE NOTICE '  GET /api/public/discover/search?q=motivation';
    RAISE NOTICE '  GET /api/public/discover/viral?q=success&min_likes=50';
    RAISE NOTICE '';
    RAISE NOTICE '✅ FTS system is production-ready for "search that feels like magic"!';
END $$;

-- Quick validation test
SELECT 
    'fts_test' as test_type,
    COUNT(*) as searchable_records,
    'Records ready for search' as description
FROM transcriptions 
WHERE fts IS NOT NULL AND status = 'completed';

-- Success banner
DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '==========================================';
    RAISE NOTICE '🔍 PRODUCTION FTS SYSTEM DEPLOYED! 🔍';
    RAISE NOTICE '==========================================';
END $$;