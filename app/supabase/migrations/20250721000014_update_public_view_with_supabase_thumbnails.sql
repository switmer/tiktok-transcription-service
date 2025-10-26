-- Update public_transcriptions view to include Supabase Storage thumbnail columns
-- This ensures the frontend can access the new persistent thumbnail URLs

-- Drop the existing view
DROP VIEW IF EXISTS public_transcriptions;

-- Recreate the view with Supabase thumbnail columns
CREATE VIEW public_transcriptions AS
SELECT 
    task_id,
    user_id,
    url,
    status,
    created_at,
    updated_at,
    video_id,
    title,
    error,
    thumbnail_url,
    thumbnail_local_path,
    supabase_thumbnail_url,  -- NEW: Supabase Storage thumbnail URL
    square_thumbnail_url,    -- NEW: Square thumbnail for social sharing
    transcript_file_path,
    callback_url,
    visibility,
    tags,
    category,
    view_count,
    last_viewed_at,
    transcript,
    -- Exclude user_phone for privacy
    source,
    metadata,
    description,
    duration,
    upload_date,
    timestamp,
    channel,
    channel_id,
    uploader,
    uploader_url,
    like_count,
    comment_count,
    repost_count,
    resolution,
    width,
    height,
    aspect_ratio,
    filesize,
    format_id,
    vcodec,
    acodec,
    audio_file_path,
    info_file_path,
    auto_tags,
    content_category,
    language,
    platform,
    video_url,
    -- Include quote and tldr columns for enhanced preview
    quote,
    tldr
FROM transcriptions
WHERE status = 'completed' 
  AND visibility = 'public';

-- Grant appropriate permissions
GRANT SELECT ON public_transcriptions TO authenticated;
GRANT SELECT ON public_transcriptions TO anon;

-- Add comment for documentation
COMMENT ON VIEW public_transcriptions IS 'Public view of completed transcriptions with Supabase Storage thumbnails, quote and tldr support, excluding sensitive user_phone data';