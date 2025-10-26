-- Fix schema mismatch: Convert view_count from INTEGER to BIGINT
-- This resolves the error: "Returned type integer does not match expected type bigint in column 7"
-- in the search_content function

-- Convert view_count column from INTEGER to BIGINT
ALTER TABLE transcriptions 
ALTER COLUMN view_count TYPE bigint;

-- Update the function comment to reflect the fix
COMMENT ON FUNCTION search_content IS 
'Lightning-fast FTS search across transcript/quote/tldr with relevance ranking (view_count fixed to bigint)';

-- Verify the change worked
DO $$
DECLARE
    view_count_type text;
BEGIN
    SELECT data_type INTO view_count_type
    FROM information_schema.columns 
    WHERE table_name = 'transcriptions' 
    AND column_name = 'view_count'
    AND table_schema = 'public';
    
    RAISE NOTICE '✅ view_count column type is now: %', view_count_type;
    
    IF view_count_type = 'bigint' THEN
        RAISE NOTICE '🎯 Schema mismatch fixed! search_content function should work now.';
    ELSE
        RAISE WARNING '⚠️ view_count type is still: %, expected bigint', view_count_type;
    END IF;
END $$;