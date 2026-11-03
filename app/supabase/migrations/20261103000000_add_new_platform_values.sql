-- Add new platform values to the transcriptions.platform CHECK constraint.
-- Previous constraint allowed: tiktok, youtube, instagram, twitter, facebook, linkedin, spotify
-- Adding: reddit, vimeo, twitch, threads, loom
-- All these platforms are now supported via yt-dlp fallback in transcriber.py

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
        'loom'
    ) OR platform IS NULL);
