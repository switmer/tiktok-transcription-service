-- Add rich metadata columns to store all TikTok/YouTube data
-- This captures the comprehensive metadata your service already extracts

-- Video content metadata
ALTER TABLE transcriptions
ADD COLUMN IF NOT EXISTS description text,
ADD COLUMN IF NOT EXISTS duration integer,  -- duration in seconds
ADD COLUMN IF NOT EXISTS upload_date text,   -- YYYYMMDD format
ADD COLUMN IF NOT EXISTS timestamp bigint,   -- original upload timestamp

-- Creator/Channel information
ADD COLUMN IF NOT EXISTS channel text,       -- creator's channel name
ADD COLUMN IF NOT EXISTS channel_id text,    -- creator's unique channel ID
ADD COLUMN IF NOT EXISTS uploader text,      -- creator's username/handle
ADD COLUMN IF NOT EXISTS uploader_url text,  -- link to creator's profile

-- Engagement metrics (TikTok)
ADD COLUMN IF NOT EXISTS like_count bigint DEFAULT 0,
ADD COLUMN IF NOT EXISTS comment_count bigint DEFAULT 0,
ADD COLUMN IF NOT EXISTS repost_count bigint DEFAULT 0,

-- Technical video specs
ADD COLUMN IF NOT EXISTS resolution text,    -- e.g. "576x1024"
ADD COLUMN IF NOT EXISTS width integer,      -- video width in pixels
ADD COLUMN IF NOT EXISTS height integer,     -- video height in pixels
ADD COLUMN IF NOT EXISTS aspect_ratio real,  -- video aspect ratio
ADD COLUMN IF NOT EXISTS filesize bigint,    -- video file size in bytes
ADD COLUMN IF NOT EXISTS format_id text,     -- video format information
ADD COLUMN IF NOT EXISTS vcodec text,        -- video codec (h264, h265, etc.)
ADD COLUMN IF NOT EXISTS acodec text,        -- audio codec (aac, etc.)

-- File paths and local storage
ADD COLUMN IF NOT EXISTS audio_file_path text,      -- path to extracted .mp3
ADD COLUMN IF NOT EXISTS info_file_path text,       -- path to .info.json file
ADD COLUMN IF NOT EXISTS transcript_file_path text, -- path to transcript file (if not already exists)

-- Enhanced content analysis
ADD COLUMN IF NOT EXISTS auto_tags text[],          -- auto-extracted tags from content
ADD COLUMN IF NOT EXISTS content_category text,     -- auto-categorized type
ADD COLUMN IF NOT EXISTS language text,             -- detected language
ADD COLUMN IF NOT EXISTS platform text DEFAULT 'tiktok';  -- source platform

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_transcriptions_uploader ON transcriptions(uploader);
CREATE INDEX IF NOT EXISTS idx_transcriptions_channel ON transcriptions(channel);
CREATE INDEX IF NOT EXISTS idx_transcriptions_duration ON transcriptions(duration);
CREATE INDEX IF NOT EXISTS idx_transcriptions_upload_date ON transcriptions(upload_date);
CREATE INDEX IF NOT EXISTS idx_transcriptions_platform ON transcriptions(platform);
CREATE INDEX IF NOT EXISTS idx_transcriptions_like_count ON transcriptions(like_count);
CREATE INDEX IF NOT EXISTS idx_transcriptions_auto_tags ON transcriptions USING GIN(auto_tags);

-- Add helpful comments
COMMENT ON COLUMN transcriptions.description IS 'Video description text from platform';
COMMENT ON COLUMN transcriptions.duration IS 'Video duration in seconds';
COMMENT ON COLUMN transcriptions.channel IS 'Creator channel name';
COMMENT ON COLUMN transcriptions.uploader IS 'Creator username/handle';
COMMENT ON COLUMN transcriptions.like_count IS 'Number of likes (TikTok)';
COMMENT ON COLUMN transcriptions.resolution IS 'Video resolution (e.g. 576x1024)';
COMMENT ON COLUMN transcriptions.audio_file_path IS 'Path to extracted MP3 audio file';
COMMENT ON COLUMN transcriptions.auto_tags IS 'Auto-extracted tags from video content';
COMMENT ON COLUMN transcriptions.platform IS 'Source platform: tiktok, youtube, etc.';

-- Verify the schema update
SELECT 
    'Rich metadata columns added' as status,
    count(*) as total_columns
FROM information_schema.columns 
WHERE table_name = 'transcriptions';

SELECT 'Rich metadata schema ready!' as result;