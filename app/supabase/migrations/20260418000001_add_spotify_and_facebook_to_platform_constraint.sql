-- Expand platform CHECK constraint to include platforms added after the original 2025 constraint.
-- Original constraint only allowed: tiktok, youtube, instagram, twitter
-- Now also allowing: spotify, facebook, linkedin (all have download paths in transcriber.py)

ALTER TABLE transcriptions DROP CONSTRAINT IF EXISTS chk_transcriptions_platform;

ALTER TABLE transcriptions
    ADD CONSTRAINT chk_transcriptions_platform
    CHECK (platform IN ('tiktok', 'youtube', 'instagram', 'twitter', 'facebook', 'linkedin', 'spotify') OR platform IS NULL);
