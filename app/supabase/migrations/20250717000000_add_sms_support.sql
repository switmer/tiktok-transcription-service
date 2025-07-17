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

-- Create transcript_jobs table for SMS workflow
CREATE TABLE IF NOT EXISTS transcript_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  from_phone text NOT NULL,
  video_url text NOT NULL,
  status text DEFAULT 'queued',
  created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
  updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
  transcript_id uuid REFERENCES transcriptions(task_id::uuid),
  error text,
  message_sid text, -- Twilio message SID for tracking
  public_link text  -- Link to public transcript page
);

-- Create user_messages table for command tracking
CREATE TABLE IF NOT EXISTS user_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  from_phone text NOT NULL,
  message_body text NOT NULL,
  command text,
  created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
  response_sent boolean DEFAULT false
);

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_transcript_jobs_from_phone ON transcript_jobs(from_phone);
CREATE INDEX IF NOT EXISTS idx_transcript_jobs_status ON transcript_jobs(status);
CREATE INDEX IF NOT EXISTS idx_user_messages_from_phone ON user_messages(from_phone);
CREATE INDEX IF NOT EXISTS idx_user_messages_command ON user_messages(command);

-- Add trigger for transcript_jobs updated_at
CREATE OR REPLACE FUNCTION update_transcript_jobs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
   NEW.updated_at = timezone('utc'::text, now());
   RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_transcript_jobs_updated_at 
BEFORE UPDATE ON transcript_jobs 
FOR EACH ROW 
EXECUTE PROCEDURE update_transcript_jobs_updated_at();

-- Comments
COMMENT ON COLUMN transcriptions.user_phone IS 'Phone number for SMS notifications and user tracking';
COMMENT ON COLUMN transcriptions.transcript IS 'Full transcript content stored directly in database';
COMMENT ON COLUMN transcriptions.category IS 'Auto-detected category (education, entertainment, etc.)';
COMMENT ON COLUMN transcriptions.tags IS 'Array of extracted tags from title/content';
COMMENT ON TABLE transcript_jobs IS 'SMS-triggered transcription jobs queue';
COMMENT ON TABLE user_messages IS 'Log of all SMS commands and interactions';