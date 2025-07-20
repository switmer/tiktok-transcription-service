#!/usr/bin/env python3
"""
Script to manually create missing SMS tables in Supabase
"""
import os
from supabase import create_client, Client

# Get Supabase credentials
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables required")
    exit(1)

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# SQL to create missing tables
sql_commands = [
    """
    CREATE TABLE IF NOT EXISTS user_messages (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      from_phone text NOT NULL,
      message_body text NOT NULL,
      command text,
      created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
      response_sent boolean DEFAULT false
    );
    """,
    """
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
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_user_messages_from_phone ON user_messages(from_phone);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sms_users_phone_number ON sms_users(phone_number);
    """
]

print("Creating missing SMS tables...")

for i, sql in enumerate(sql_commands, 1):
    try:
        result = supabase.rpc('exec_sql', {'sql': sql.strip()})
        print(f"✅ Command {i}: Success")
    except Exception as e:
        # Try direct SQL execution
        try:
            # Use raw SQL execution
            result = supabase.postgrest.rpc('exec_sql', {'sql': sql.strip()}).execute()
            print(f"✅ Command {i}: Success (fallback)")
        except Exception as e2:
            print(f"❌ Command {i}: Failed - {str(e2)}")

print("\nChecking if tables exist...")

# Check if tables were created
try:
    # Check user_messages table
    result = supabase.table('user_messages').select('*').limit(1).execute()
    print("✅ user_messages table exists")
except Exception as e:
    print(f"❌ user_messages table missing: {str(e)}")

try:
    # Check sms_users table  
    result = supabase.table('sms_users').select('*').limit(1).execute()
    print("✅ sms_users table exists")
except Exception as e:
    print(f"❌ sms_users table missing: {str(e)}")

print("Done!")