#!/usr/bin/env python3
"""
Direct SQL execution to create user_messages table
"""
import os
import requests

# Get Supabase credentials
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables required")
    exit(1)

# Use Supabase REST API to execute SQL directly
sql = """
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
"""

print("Creating user_messages table via direct SQL...")
print(f"SQL: {sql}")

# Try to execute via Supabase REST API
headers = {
    'apikey': SUPABASE_SERVICE_KEY,
    'Authorization': f'Bearer {SUPABASE_SERVICE_KEY}',
    'Content-Type': 'application/json'
}

# Try the RPC endpoint
rpc_url = f"{SUPABASE_URL}/rest/v1/rpc/exec_sql"
data = {'sql': sql}

try:
    response = requests.post(rpc_url, headers=headers, json=data)
    print(f"RPC Response: {response.status_code} - {response.text}")
except Exception as e:
    print(f"RPC failed: {e}")

print("Done!")