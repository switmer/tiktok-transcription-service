-- Add SMS support to transcriptions table
ALTER TABLE transcriptions 
ADD COLUMN IF NOT EXISTS user_phone text NULL;

-- Add index for faster lookups by phone number
CREATE INDEX IF NOT EXISTS idx_transcriptions_user_phone 
ON transcriptions(user_phone);

-- Add column for storing transcript content directly
ALTER TABLE transcriptions 
ADD COLUMN IF NOT EXISTS transcript text NULL;

-- Add columns for categorization and tags
ALTER TABLE transcriptions 
ADD COLUMN IF NOT EXISTS category text NULL,
ADD COLUMN IF NOT EXISTS tags text[] NULL;

-- Comment to explain the changes
COMMENT ON COLUMN transcriptions.user_phone IS 'Phone number for SMS notifications and user tracking';
COMMENT ON COLUMN transcriptions.transcript IS 'Full transcript content stored directly in database';
COMMENT ON COLUMN transcriptions.category IS 'Auto-detected category (education, entertainment, etc.)';
COMMENT ON COLUMN transcriptions.tags IS 'Array of extracted tags from title/content';