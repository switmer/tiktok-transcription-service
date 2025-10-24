-- Add unique constraint to message_sid column in user_messages table
-- This fixes the ON CONFLICT error in safe_message_log function

-- First, clean up any duplicate message_sid values (keep the oldest)
DELETE FROM user_messages a
USING user_messages b
WHERE a.id > b.id
  AND a.message_sid = b.message_sid
  AND a.message_sid IS NOT NULL;

-- Add unique constraint (allows NULL values)
ALTER TABLE user_messages 
ADD CONSTRAINT user_messages_message_sid_unique 
UNIQUE (message_sid);

-- Add index for faster lookups
CREATE INDEX IF NOT EXISTS idx_user_messages_message_sid 
ON user_messages(message_sid) 
WHERE message_sid IS NOT NULL;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Added unique constraint to user_messages.message_sid';
    RAISE NOTICE 'ON CONFLICT (message_sid) will now work properly in safe_message_log function.';
END $$;

