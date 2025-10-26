-- Add Supabase Storage thumbnail columns
-- supabase_thumbnail_url: Primary thumbnail stored in Supabase Storage
-- square_thumbnail_url: Square thumbnail for optimal social media sharing

ALTER TABLE transcriptions 
ADD COLUMN IF NOT EXISTS supabase_thumbnail_url text NULL,
ADD COLUMN IF NOT EXISTS square_thumbnail_url text NULL;

-- Add comment for clarity
COMMENT ON COLUMN transcriptions.supabase_thumbnail_url IS 'Primary thumbnail URL stored in Supabase Storage (persistent)';
COMMENT ON COLUMN transcriptions.square_thumbnail_url IS 'Square (1:1) thumbnail URL for optimal social media sharing';
COMMENT ON COLUMN transcriptions.thumbnail_url IS 'External thumbnail URL (e.g., TikTok CDN)';
COMMENT ON COLUMN transcriptions.thumbnail_local_path IS 'Local thumbnail path (ephemeral, may not exist after restarts)';