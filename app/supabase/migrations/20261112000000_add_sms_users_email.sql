-- Optional email on sms_users so web/email accounts can share the same
-- credit balance table as phone-first SMS users.
-- DO NOT apply from CI/agents against production; ship via normal migrate process.

ALTER TABLE sms_users
ADD COLUMN IF NOT EXISTS email text;

-- Case-insensitive uniqueness for non-null emails
CREATE UNIQUE INDEX IF NOT EXISTS idx_sms_users_email_unique
ON sms_users (lower(email))
WHERE email IS NOT NULL AND length(trim(email)) > 0;

CREATE INDEX IF NOT EXISTS idx_sms_users_email
ON sms_users (email)
WHERE email IS NOT NULL;

COMMENT ON COLUMN sms_users.email IS
  'Optional email for users who also have a web/email identity; credits remain keyed primarily by phone_number/auth_user_id';
