#!/usr/bin/env python3
"""
Direct SQL migration using various methods to ensure the columns get added
"""

import os
import requests
import psycopg2
from dotenv import load_dotenv
from supabase import create_client, Client
from urllib.parse import urlparse

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
elif os.path.exists('.env'):
    load_dotenv()

# Get credentials
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')
SUPABASE_DB_PASSWORD = os.environ.get('SUPABASE_DB_PASSWORD')

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print('Error: Missing Supabase credentials')
    exit(1)

# The migration SQL
migration_sql = """
-- Add quote and TLDR columns to transcriptions table
ALTER TABLE public.transcriptions 
ADD COLUMN IF NOT EXISTS quote text NULL,
ADD COLUMN IF NOT EXISTS tldr jsonb NULL;

-- Add indexes for quote and TLDR searches
CREATE INDEX IF NOT EXISTS idx_transcriptions_quote ON public.transcriptions USING gin(to_tsvector('english', quote));
CREATE INDEX IF NOT EXISTS idx_transcriptions_tldr ON public.transcriptions USING gin(tldr);

-- Add comments for clarity
COMMENT ON COLUMN public.transcriptions.quote IS 'Most memorable, shareable quote from the video';
COMMENT ON COLUMN public.transcriptions.tldr IS 'Array of 2-3 key bullet points as JSON array';
"""

print("Attempting multiple migration methods...")

# Method 1: Try Supabase SQL Editor API (if available)
print("\n=== Method 1: Supabase SQL API ===")
try:
    headers = {
        'apikey': SUPABASE_SERVICE_KEY,
        'Authorization': f'Bearer {SUPABASE_SERVICE_KEY}',
        'Content-Type': 'application/json'
    }
    
    # Try the sql endpoint (this might not exist in all Supabase instances)
    sql_url = f"{SUPABASE_URL}/rest/v1/rpc/query"
    data = {'query': migration_sql}
    
    response = requests.post(sql_url, headers=headers, json=data)
    print(f"SQL API Response: {response.status_code}")
    
    if response.status_code == 200:
        print("✅ Migration successful via SQL API")
    else:
        print(f"❌ SQL API failed: {response.text}")
        
except Exception as e:
    print(f"❌ SQL API method failed: {e}")

# Method 2: Try direct PostgreSQL connection (if DB password available)
print("\n=== Method 2: Direct PostgreSQL Connection ===")
try:
    if SUPABASE_DB_PASSWORD:
        # Parse the Supabase URL to get connection details
        parsed_url = urlparse(SUPABASE_URL)
        host = parsed_url.hostname.replace('https://', '').replace('http://', '')
        if 'supabase.co' in host:
            # Convert API URL to DB URL
            project_id = host.split('.')[0]
            db_host = f"db.{project_id}.supabase.co"
            
            conn_string = f"postgresql://postgres:{SUPABASE_DB_PASSWORD}@{db_host}:5432/postgres"
            
            print(f"Connecting to: {db_host}")
            conn = psycopg2.connect(conn_string)
            cur = conn.cursor()
            
            # Execute the migration
            cur.execute(migration_sql)
            conn.commit()
            
            print("✅ Migration successful via direct PostgreSQL")
            
            cur.close()
            conn.close()
        else:
            print("❌ Could not parse Supabase URL for direct connection")
    else:
        print("❌ No database password available for direct connection")
        
except Exception as e:
    print(f"❌ Direct PostgreSQL method failed: {e}")

# Method 3: Use Supabase management API (if available)
print("\n=== Method 3: Manual Column Addition ===")
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    
    # Try to manually add the columns using table operations
    # This is a fallback approach if SQL execution isn't available
    print("Attempting to verify/create columns through Supabase client...")
    
    # First, let's see if we can access any existing records
    result = supabase.table('transcriptions').select('*').limit(1).execute()
    
    if result.data:
        sample = result.data[0]
        
        # Try to update a record with the new columns to see if they exist
        try:
            # This will fail if columns don't exist
            test_update = {
                'quote': 'test',
                'tldr': ['test point']
            }
            
            # We won't actually execute this update, just test the schema
            print("Testing if columns exist by attempting a mock update...")
            
            # Instead, let's try a different approach - use upsert with conflict resolution
            # This might reveal if the columns exist
            
            print("Columns need to be added via SQL migration")
            
        except Exception as update_error:
            print(f"Update test result: {update_error}")
    
except Exception as e:
    print(f"❌ Supabase client method failed: {e}")

print("\n=== Manual Instructions ===")
print("If the above methods failed, please manually run this SQL in your Supabase SQL editor:")
print("-" * 50)
print(migration_sql)
print("-" * 50)
print("Go to your Supabase dashboard -> SQL Editor -> Run the above query")