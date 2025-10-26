#!/usr/bin/env python3
"""
HTTP-based migration using Supabase REST API
"""

import os
import requests
from dotenv import load_dotenv

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
elif os.path.exists('.env'):
    load_dotenv()

# Get credentials
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print('Error: Missing Supabase credentials')
    exit(1)

print(f"Using Supabase URL: {SUPABASE_URL}")

# Set up headers for API requests
headers = {
    'apikey': SUPABASE_SERVICE_KEY,
    'Authorization': f'Bearer {SUPABASE_SERVICE_KEY}',
    'Content-Type': 'application/json',
    'Prefer': 'return=minimal'
}

# Individual SQL statements
sql_statements = [
    "ALTER TABLE public.transcriptions ADD COLUMN IF NOT EXISTS quote text NULL, ADD COLUMN IF NOT EXISTS tldr jsonb NULL;",
    "CREATE INDEX IF NOT EXISTS idx_transcriptions_quote ON public.transcriptions USING gin(to_tsvector('english', quote));",
    "CREATE INDEX IF NOT EXISTS idx_transcriptions_tldr ON public.transcriptions USING gin(tldr);",
    "COMMENT ON COLUMN public.transcriptions.quote IS 'Most memorable, shareable quote from the video';",
    "COMMENT ON COLUMN public.transcriptions.tldr IS 'Array of 2-3 key bullet points as JSON array';"
]

print(f"Executing {len(sql_statements)} SQL statements via HTTP API...")

success_count = 0

for i, sql in enumerate(sql_statements, 1):
    print(f"\nStatement {i}: {sql[:80]}...")
    
    # Try multiple endpoints
    endpoints_to_try = [
        f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
        f"{SUPABASE_URL}/rest/v1/rpc/query",
        f"{SUPABASE_URL}/sql/v1/query"
    ]
    
    statement_success = False
    
    for endpoint in endpoints_to_try:
        try:
            data = {'sql': sql}
            response = requests.post(endpoint, headers=headers, json=data)
            
            print(f"  Trying {endpoint.split('/')[-1]}: {response.status_code}")
            
            if response.status_code in [200, 201, 204]:
                print(f"  ✅ Success via {endpoint.split('/')[-1]}")
                statement_success = True
                success_count += 1
                break
            else:
                print(f"  ❌ Failed: {response.text[:100]}")
                
        except Exception as e:
            print(f"  ❌ Error: {str(e)[:100]}")
            
    if not statement_success:
        print(f"  ❌ Statement {i} failed on all endpoints")

print(f"\nMigration summary: {success_count}/{len(sql_statements)} statements executed successfully")

# Verify the results
print("\n=== Verification ===")
try:
    from supabase import create_client
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    
    # Check table structure
    result = supabase.table('transcriptions').select('*').limit(1).execute()
    if result.data:
        keys = list(result.data[0].keys())
        
        if 'quote' in keys and 'tldr' in keys:
            print("✅ Both quote and tldr columns found!")
        elif 'quote' in keys:
            print("✅ quote column found, tldr missing")
        elif 'tldr' in keys:
            print("✅ tldr column found, quote missing")
        else:
            print("❌ Neither column found")
            print(f"Available columns: {sorted(keys)}")
    else:
        print("No data to verify with")
        
except Exception as e:
    print(f"Verification error: {e}")
    
if success_count == 0:
    print("\n🔧 MANUAL MIGRATION REQUIRED 🔧")
    print("The automatic migration failed. Please manually run the following SQL")
    print("in your Supabase dashboard -> SQL Editor:")
    print("-" * 60)
    print("ALTER TABLE public.transcriptions")
    print("ADD COLUMN IF NOT EXISTS quote text NULL,")
    print("ADD COLUMN IF NOT EXISTS tldr jsonb NULL;")
    print()
    print("CREATE INDEX IF NOT EXISTS idx_transcriptions_quote ON public.transcriptions USING gin(to_tsvector('english', quote));")
    print("CREATE INDEX IF NOT EXISTS idx_transcriptions_tldr ON public.transcriptions USING gin(tldr);")
    print()
    print("COMMENT ON COLUMN public.transcriptions.quote IS 'Most memorable, shareable quote from the video';")
    print("COMMENT ON COLUMN public.transcriptions.tldr IS 'Array of 2-3 key bullet points as JSON array';")
    print("-" * 60)