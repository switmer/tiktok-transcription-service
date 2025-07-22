-- Clean up any existing problematic indexes that might cause row size issues
-- This migration should run before adding the new optimized indexes

-- Drop any existing indexes that might have large row sizes
DROP INDEX IF EXISTS idx_transcriptions_failed;
DROP INDEX IF EXISTS idx_transcriptions_quote_text;
DROP INDEX IF EXISTS idx_transcriptions_transcript_fts;

-- Drop any other potentially problematic indexes on large text fields
DROP INDEX IF EXISTS idx_transcriptions_error;
DROP INDEX IF EXISTS idx_transcriptions_transcript;
DROP INDEX IF EXISTS idx_transcriptions_description;

-- Success message
DO $$
BEGIN
    RAISE NOTICE 'Cleaned up potentially problematic large indexes';
    RAISE NOTICE 'Ready for optimized index creation in next migration';
END $$;