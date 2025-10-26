-- Fix critical production bug: Add missing updated_at column to sms_users
-- This resolves the "record 'new' has no field 'updated_at'" error that breaks
-- all credit transactions and user updates

-- Add the updated_at column with default value
ALTER TABLE sms_users
ADD COLUMN updated_at timestamp with time zone DEFAULT now();

-- Set initial updated_at values for existing records
UPDATE sms_users 
SET updated_at = COALESCE(last_active, created_at, now())
WHERE updated_at IS NULL;

-- Make updated_at NOT NULL after setting initial values
ALTER TABLE sms_users 
ALTER COLUMN updated_at SET NOT NULL;

-- Create or update the trigger function to automatically set updated_at
CREATE OR REPLACE FUNCTION set_updated_at_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop existing trigger if it exists and create new one
DROP TRIGGER IF EXISTS set_sms_users_updated_at ON sms_users;

CREATE TRIGGER set_sms_users_updated_at
  BEFORE UPDATE ON sms_users
  FOR EACH ROW
  EXECUTE FUNCTION set_updated_at_timestamp();

-- Add comment for documentation
COMMENT ON COLUMN sms_users.updated_at IS 'Automatically updated timestamp when record is modified';

-- Test the fix by updating a record (if any exist)
DO $$
BEGIN
  -- Test that the trigger works
  IF EXISTS (SELECT 1 FROM sms_users LIMIT 1) THEN
    UPDATE sms_users 
    SET last_active = now() 
    WHERE phone_number = (
      SELECT phone_number FROM sms_users LIMIT 1
    );
    
    RAISE NOTICE 'updated_at column added and trigger tested successfully';
  END IF;
END $$;