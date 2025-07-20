#!/usr/bin/env python3
"""
Manually create user_messages table using psycopg2
"""
import os
import psycopg2
from urllib.parse import urlparse

# Parse database URL
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL:
    print("Error: SUPABASE_URL required")
    exit(1)

# Extract project ref from URL
project_ref = SUPABASE_URL.replace("https://", "").replace(".supabase.co", "")
print(f"Project ref: {project_ref}")

# You'll need to get the direct database password from your Supabase dashboard
# Under Settings -> Database -> Connection string
print("To create the user_messages table, you need to:")
print("1. Go to your Supabase dashboard")
print("2. Navigate to Settings -> Database") 
print("3. Open the SQL Editor")
print("4. Run this SQL:")
print()
print("""
CREATE TABLE IF NOT EXISTS user_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  from_phone text NOT NULL,
  message_body text NOT NULL,
  command text,
  created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
  response_sent boolean DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_user_messages_from_phone ON user_messages(from_phone);
CREATE INDEX IF NOT EXISTS idx_user_messages_command ON user_messages(command);
""")
print()
print("This will create the missing user_messages table that your Edge Function needs.")