-- Migration: Add video_url column for storing direct CDN video links
-- Created: 2025-07-20

-- Add video_url column to transcriptions table
ALTER TABLE transcriptions 
ADD COLUMN IF NOT EXISTS video_url text NULL;

-- Add index for video_url column for faster lookups
CREATE INDEX IF NOT EXISTS idx_transcriptions_video_url ON transcriptions(video_url);

-- Add comment for documentation
COMMENT ON COLUMN transcriptions.video_url IS 'Direct CDN video URL from TikTok/YouTube for streaming without re-downloading';

-- Insert migration record
INSERT INTO schema_migrations (version, applied_at) 
VALUES ('20250720000000_add_video_url_column', NOW())
ON CONFLICT (version) DO NOTHING;