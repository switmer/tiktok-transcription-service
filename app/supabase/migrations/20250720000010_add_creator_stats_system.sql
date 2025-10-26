-- Add creator stats and TikTok profile linking system

-- Add TikTok profile fields to sms_users table
ALTER TABLE sms_users 
ADD COLUMN IF NOT EXISTS tiktok_handle TEXT,
ADD COLUMN IF NOT EXISTS tiktok_profile_url TEXT,
ADD COLUMN IF NOT EXISTS tiktok_linked_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS total_videos_transcribed INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS most_popular_video_id TEXT,
ADD COLUMN IF NOT EXISTS most_popular_video_views INTEGER DEFAULT 0;

-- Create user_video_stats table for tracking transcribed videos
CREATE TABLE IF NOT EXISTS user_video_stats (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_phone TEXT NOT NULL REFERENCES sms_users(phone_number),
    video_id TEXT NOT NULL,
    video_url TEXT NOT NULL,
    video_title TEXT,
    video_author TEXT,
    video_author_handle TEXT,
    view_count INTEGER,
    like_count INTEGER,
    comment_count INTEGER,
    share_count INTEGER,
    transcribed_at TIMESTAMPTZ DEFAULT NOW(),
    is_users_video BOOLEAN DEFAULT FALSE, -- True if this video belongs to the user
    UNIQUE(user_phone, video_id)
);

-- Create tiktok_profile_stats table for tracking creator growth (future feature)
CREATE TABLE IF NOT EXISTS tiktok_profile_stats (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tiktok_handle TEXT NOT NULL,
    follower_count INTEGER,
    following_count INTEGER,
    total_likes INTEGER,
    total_videos INTEGER,
    verified BOOLEAN DEFAULT FALSE,
    snapshot_date TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tiktok_handle, snapshot_date::DATE)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_sms_users_tiktok_handle ON sms_users(tiktok_handle);
CREATE INDEX IF NOT EXISTS idx_user_video_stats_user_phone ON user_video_stats(user_phone);
CREATE INDEX IF NOT EXISTS idx_user_video_stats_video_id ON user_video_stats(video_id);
CREATE INDEX IF NOT EXISTS idx_user_video_stats_is_users_video ON user_video_stats(is_users_video);
CREATE INDEX IF NOT EXISTS idx_user_video_stats_transcribed_at ON user_video_stats(transcribed_at DESC);
CREATE INDEX IF NOT EXISTS idx_tiktok_profile_stats_handle ON tiktok_profile_stats(tiktok_handle);
CREATE INDEX IF NOT EXISTS idx_tiktok_profile_stats_snapshot_date ON tiktok_profile_stats(snapshot_date DESC);

-- Function to extract TikTok handle from various formats
CREATE OR REPLACE FUNCTION extract_tiktok_handle(input_text TEXT)
RETURNS TEXT AS $$
DECLARE
    handle TEXT;
BEGIN
    -- Remove any leading/trailing whitespace
    input_text := TRIM(input_text);
    
    -- If it's a TikTok URL, extract the handle
    handle := SUBSTRING(input_text FROM 'tiktok\.com/@([a-zA-Z0-9_.]+)');
    
    IF handle IS NOT NULL THEN
        RETURN handle;
    END IF;
    
    -- If it starts with @, remove it
    IF LEFT(input_text, 1) = '@' THEN
        RETURN SUBSTRING(input_text FROM 2);
    END IF;
    
    -- Otherwise, return as-is (assuming it's already a clean handle)
    RETURN input_text;
END;
$$ LANGUAGE plpgsql;

-- Function to link TikTok profile to user
CREATE OR REPLACE FUNCTION link_tiktok_profile(user_phone TEXT, handle_or_url TEXT)
RETURNS TABLE (
    success BOOLEAN,
    handle TEXT,
    message TEXT
) AS $$
DECLARE
    clean_handle TEXT;
BEGIN
    -- Extract clean handle from input
    clean_handle := extract_tiktok_handle(handle_or_url);
    
    -- Validate handle format (basic check)
    IF clean_handle IS NULL OR LENGTH(clean_handle) < 1 OR LENGTH(clean_handle) > 30 THEN
        RETURN QUERY SELECT FALSE, NULL::TEXT, 'Invalid TikTok handle format';
        RETURN;
    END IF;
    
    -- Update user's TikTok profile info
    UPDATE sms_users 
    SET 
        tiktok_handle = clean_handle,
        tiktok_profile_url = CASE 
            WHEN handle_or_url LIKE '%tiktok.com%' THEN handle_or_url
            ELSE 'https://www.tiktok.com/@' || clean_handle
        END,
        tiktok_linked_at = NOW()
    WHERE phone_number = user_phone;
    
    -- Mark all existing videos from this handle as user's videos
    UPDATE user_video_stats 
    SET is_users_video = TRUE
    WHERE user_phone = user_phone 
        AND video_author_handle = clean_handle;
    
    RETURN QUERY SELECT TRUE, clean_handle, 'TikTok profile linked successfully';
END;
$$ LANGUAGE plpgsql;

-- Function to get user's comprehensive stats
CREATE OR REPLACE FUNCTION get_user_creator_stats(user_phone TEXT)
RETURNS TABLE (
    total_transcribed INTEGER,
    credits_remaining INTEGER,
    free_credits_used INTEGER,
    total_referrals INTEGER,
    total_referral_credits INTEGER,
    tiktok_handle TEXT,
    tiktok_linked BOOLEAN,
    joined_date TIMESTAMPTZ,
    most_popular_video JSONB,
    top_creators JSONB,
    recent_videos JSONB
) AS $$
DECLARE
    user_data RECORD;
    popular_video JSONB;
    top_creators_data JSONB;
    recent_videos_data JSONB;
BEGIN
    -- Get user basic data
    SELECT 
        COALESCE(su.total_videos_transcribed, 0) as transcribed,
        COALESCE(su.credits_remaining, 0) as credits,
        COALESCE(su.free_credits_used, 0) as free_used,
        COALESCE(su.referrals_count, 0) as referrals,
        COALESCE(su.total_referral_credits_earned, 0) as referral_credits,
        su.tiktok_handle,
        su.tiktok_linked_at IS NOT NULL as linked,
        su.created_at as joined
    INTO user_data
    FROM sms_users su
    WHERE su.phone_number = user_phone;
    
    -- Get most popular video transcribed by user
    SELECT JSONB_BUILD_OBJECT(
        'title', uvs.video_title,
        'author', uvs.video_author,
        'views', uvs.view_count,
        'likes', uvs.like_count,
        'transcribed_at', uvs.transcribed_at
    ) INTO popular_video
    FROM user_video_stats uvs
    WHERE uvs.user_phone = user_phone
        AND uvs.view_count IS NOT NULL
    ORDER BY uvs.view_count DESC
    LIMIT 1;
    
    -- Get top creators they've transcribed
    SELECT JSONB_AGG(
        JSONB_BUILD_OBJECT(
            'handle', uvs.video_author_handle,
            'name', uvs.video_author,
            'count', creator_stats.video_count
        )
        ORDER BY creator_stats.video_count DESC
    ) INTO top_creators_data
    FROM (
        SELECT 
            uvs.video_author_handle,
            uvs.video_author,
            COUNT(*) as video_count
        FROM user_video_stats uvs
        WHERE uvs.user_phone = user_phone
            AND uvs.video_author_handle IS NOT NULL
        GROUP BY uvs.video_author_handle, uvs.video_author
        ORDER BY COUNT(*) DESC
        LIMIT 3
    ) creator_stats
    JOIN user_video_stats uvs ON uvs.video_author_handle = creator_stats.video_author_handle
        AND uvs.user_phone = user_phone;
    
    -- Get recent videos (last 5)
    SELECT JSONB_AGG(
        JSONB_BUILD_OBJECT(
            'title', uvs.video_title,
            'author', uvs.video_author,
            'views', uvs.view_count,
            'transcribed_at', uvs.transcribed_at,
            'is_mine', uvs.is_users_video
        )
        ORDER BY uvs.transcribed_at DESC
    ) INTO recent_videos_data
    FROM user_video_stats uvs
    WHERE uvs.user_phone = user_phone
    ORDER BY uvs.transcribed_at DESC
    LIMIT 5;
    
    RETURN QUERY SELECT 
        COALESCE(user_data.transcribed, 0),
        COALESCE(user_data.credits, 0),
        COALESCE(user_data.free_used, 0),
        COALESCE(user_data.referrals, 0),
        COALESCE(user_data.referral_credits, 0),
        user_data.tiktok_handle,
        COALESCE(user_data.linked, FALSE),
        user_data.joined,
        COALESCE(popular_video, '{}'::JSONB),
        COALESCE(top_creators_data, '[]'::JSONB),
        COALESCE(recent_videos_data, '[]'::JSONB);
END;
$$ LANGUAGE plpgsql;

-- Function to record video transcription stats
CREATE OR REPLACE FUNCTION record_video_transcription(
    user_phone TEXT,
    video_id TEXT,
    video_url TEXT,
    video_title TEXT DEFAULT NULL,
    video_author TEXT DEFAULT NULL,
    video_author_handle TEXT DEFAULT NULL,
    view_count INTEGER DEFAULT NULL,
    like_count INTEGER DEFAULT NULL,
    comment_count INTEGER DEFAULT NULL,
    share_count INTEGER DEFAULT NULL
)
RETURNS VOID AS $$
DECLARE
    is_users_video BOOLEAN := FALSE;
    user_handle TEXT;
BEGIN
    -- Get user's TikTok handle to check if this is their video
    SELECT tiktok_handle INTO user_handle
    FROM sms_users
    WHERE phone_number = user_phone;
    
    -- Check if this video belongs to the user
    IF user_handle IS NOT NULL AND video_author_handle IS NOT NULL THEN
        is_users_video := (user_handle = video_author_handle);
    END IF;
    
    -- Insert or update video stats
    INSERT INTO user_video_stats (
        user_phone, video_id, video_url, video_title, video_author, 
        video_author_handle, view_count, like_count, comment_count, 
        share_count, is_users_video
    )
    VALUES (
        user_phone, video_id, video_url, video_title, video_author,
        video_author_handle, view_count, like_count, comment_count,
        share_count, is_users_video
    )
    ON CONFLICT (user_phone, video_id) 
    DO UPDATE SET
        video_title = COALESCE(EXCLUDED.video_title, user_video_stats.video_title),
        video_author = COALESCE(EXCLUDED.video_author, user_video_stats.video_author),
        video_author_handle = COALESCE(EXCLUDED.video_author_handle, user_video_stats.video_author_handle),
        view_count = COALESCE(EXCLUDED.view_count, user_video_stats.view_count),
        like_count = COALESCE(EXCLUDED.like_count, user_video_stats.like_count),
        comment_count = COALESCE(EXCLUDED.comment_count, user_video_stats.comment_count),
        share_count = COALESCE(EXCLUDED.share_count, user_video_stats.share_count),
        is_users_video = EXCLUDED.is_users_video;
    
    -- Update user's total transcribed count
    UPDATE sms_users 
    SET total_videos_transcribed = (
        SELECT COUNT(*) FROM user_video_stats WHERE user_phone = sms_users.phone_number
    )
    WHERE phone_number = user_phone;
    
    -- Update most popular video if this one is bigger
    UPDATE sms_users 
    SET 
        most_popular_video_id = video_id,
        most_popular_video_views = view_count
    WHERE phone_number = user_phone
        AND (most_popular_video_views IS NULL OR view_count > most_popular_video_views);
END;
$$ LANGUAGE plpgsql;

-- Add RLS policies for new tables
ALTER TABLE user_video_stats ENABLE ROW LEVEL SECURITY;
ALTER TABLE tiktok_profile_stats ENABLE ROW LEVEL SECURITY;

-- Service role can access all records
CREATE POLICY "Service role can access all video stats" ON user_video_stats
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Service role can access all profile stats" ON tiktok_profile_stats
    FOR ALL USING (auth.role() = 'service_role');

-- Users can see their own video stats (if authenticated)
CREATE POLICY "Users can view their own video stats" ON user_video_stats
    FOR SELECT USING (
        auth.role() = 'authenticated' AND 
        user_phone = (SELECT phone_number FROM sms_users WHERE auth_user_id = auth.uid())
    );

COMMENT ON TABLE user_video_stats IS 'Track all videos transcribed by each user with metadata';
COMMENT ON TABLE tiktok_profile_stats IS 'Historical TikTok profile stats for growth tracking';
COMMENT ON FUNCTION extract_tiktok_handle IS 'Extract clean handle from TikTok URLs or @handles';
COMMENT ON FUNCTION link_tiktok_profile IS 'Link user to their TikTok profile';
COMMENT ON FUNCTION get_user_creator_stats IS 'Get comprehensive creator stats for dashboard';
COMMENT ON FUNCTION record_video_transcription IS 'Record video transcription with metadata for stats';

SELECT 'Creator stats system added successfully' as result;