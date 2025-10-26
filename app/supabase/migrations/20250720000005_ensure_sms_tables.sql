-- Ensure SMS tables exist (in case previous migrations didn't actually run)

-- Create user_messages table for command tracking  
CREATE TABLE IF NOT EXISTS user_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  from_phone text NOT NULL,
  message_body text NOT NULL,
  command text,
  created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
  response_sent boolean DEFAULT false
);

-- Create sms_users table for SMS authentication and user management
CREATE TABLE IF NOT EXISTS sms_users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_number text UNIQUE NOT NULL,
  auth_user_id uuid NULL,
  phone_verified boolean DEFAULT false,
  verification_code text NULL,
  verification_expires timestamp with time zone NULL,
  session_token text NULL,
  session_expires timestamp with time zone NULL,
  total_transcriptions integer DEFAULT 0,
  monthly_transcriptions integer DEFAULT 0,
  last_active timestamp with time zone DEFAULT timezone('utc'::text, now()),
  created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
  updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Create transcript_jobs table for SMS workflow
CREATE TABLE IF NOT EXISTS transcript_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  from_phone text NOT NULL,
  video_url text NOT NULL,
  status text DEFAULT 'queued',
  created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
  updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
  transcript_id uuid,
  error text,
  message_sid text,
  public_link text
);

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_user_messages_from_phone ON user_messages(from_phone);
CREATE INDEX IF NOT EXISTS idx_user_messages_command ON user_messages(command);
CREATE INDEX IF NOT EXISTS idx_sms_users_phone_number ON sms_users(phone_number);
CREATE INDEX IF NOT EXISTS idx_sms_users_auth_user_id ON sms_users(auth_user_id);
CREATE INDEX IF NOT EXISTS idx_transcript_jobs_from_phone ON transcript_jobs(from_phone);
CREATE INDEX IF NOT EXISTS idx_transcript_jobs_status ON transcript_jobs(status);

-- Ensure functions exist
CREATE OR REPLACE FUNCTION get_sms_user_stats(p_phone_number text)
RETURNS TABLE (
  total_transcriptions bigint,
  monthly_transcriptions bigint,
  verified boolean,
  joined_date timestamp with time zone
) AS $$
BEGIN
  RETURN QUERY
  SELECT 
    COALESCE(COUNT(t.task_id), 0) as total_transcriptions,
    COALESCE(COUNT(t.task_id) FILTER (WHERE t.created_at >= date_trunc('month', NOW())), 0) as monthly_transcriptions,
    COALESCE(s.phone_verified, false) as verified,
    COALESCE(s.created_at, NOW()) as joined_date
  FROM transcriptions t
  RIGHT JOIN sms_users s ON s.phone_number = p_phone_number
  WHERE t.user_phone = p_phone_number OR t.user_phone IS NULL
  GROUP BY s.phone_verified, s.created_at;
  
  IF NOT FOUND THEN
    RETURN QUERY
    SELECT 
      0::bigint as total_transcriptions,
      0::bigint as monthly_transcriptions, 
      false as verified,
      NOW() as joined_date;
  END IF;
END;
$$ LANGUAGE plpgsql;

SELECT 'SMS tables and functions ensured' as result;