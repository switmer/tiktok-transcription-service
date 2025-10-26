-- Create sms_users table for SMS authentication and user management
CREATE TABLE IF NOT EXISTS sms_users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_number text UNIQUE NOT NULL,
  auth_user_id uuid NULL, -- Link to auth.users if they upgrade to web account
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

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_sms_users_phone_number ON sms_users(phone_number);
CREATE INDEX IF NOT EXISTS idx_sms_users_auth_user_id ON sms_users(auth_user_id);
CREATE INDEX IF NOT EXISTS idx_sms_users_session_token ON sms_users(session_token);
CREATE INDEX IF NOT EXISTS idx_sms_users_verification_code ON sms_users(verification_code);

-- Add trigger for sms_users updated_at
CREATE OR REPLACE FUNCTION update_sms_users_updated_at()
RETURNS TRIGGER AS $$
BEGIN
   NEW.updated_at = timezone('utc'::text, now());
   RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_sms_users_updated_at 
BEFORE UPDATE ON sms_users 
FOR EACH ROW 
EXECUTE PROCEDURE update_sms_users_updated_at();

-- Comments
COMMENT ON TABLE sms_users IS 'SMS users for phone-first authentication system';
COMMENT ON COLUMN sms_users.phone_number IS 'Normalized phone number (+1XXXXXXXXXX format)';
COMMENT ON COLUMN sms_users.auth_user_id IS 'Link to Supabase auth.users if user upgrades to web account';
COMMENT ON COLUMN sms_users.phone_verified IS 'Whether phone number has been verified via OTP';
COMMENT ON COLUMN sms_users.verification_code IS 'Current OTP code for verification';
COMMENT ON COLUMN sms_users.verification_expires IS 'When current OTP expires';
COMMENT ON COLUMN sms_users.session_token IS 'Session token for authenticated SMS users';
COMMENT ON COLUMN sms_users.session_expires IS 'When session token expires';
COMMENT ON COLUMN sms_users.total_transcriptions IS 'Total number of transcriptions for this user';
COMMENT ON COLUMN sms_users.monthly_transcriptions IS 'Number of transcriptions this month';