-- Add 'web' platform value to the transcriptions.platform CHECK constraint.
-- This is used when ScribeTok discovers a video on a generic web page that isn't
-- one of the known platforms, and the video is from an unknown source.
-- Note: If the discovered video is from a known platform (e.g. YouTube embed),
-- the actual platform value will be used instead.

ALTER TABLE transcriptions DROP CONSTRAINT IF EXISTS chk_transcriptions_platform;

ALTER TABLE transcriptions
    ADD CONSTRAINT chk_transcriptions_platform
    CHECK (platform IN (
        'tiktok',
        'youtube',
        'instagram',
        'twitter',   -- X/Twitter stored as 'twitter'
        'facebook',
        'linkedin',
        'spotify',
        'reddit',
        'vimeo',
        'twitch',
        'threads',
        'loom',
        'web'        -- Generic web page video (e.g. direct .mp4 link)
    ) OR platform IS NULL);
