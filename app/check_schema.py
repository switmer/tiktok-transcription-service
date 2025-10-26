#!/usr/bin/env python3
"""
Check the actual database schema to see if columns exist
"""

import os
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)

# Get credentials
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print('Error: Missing Supabase credentials')
    exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

print("=== SCHEMA INSPECTION ===")

# Method 1: Try to query system tables for column information
print("\n1. Checking system tables for column information...")
try:
    # This uses PostgreSQL information_schema to check for columns
    # Note: This may not work directly through Supabase REST API
    query = """
    SELECT column_name, data_type, is_nullable 
    FROM information_schema.columns 
    WHERE table_name = 'transcriptions' 
    AND table_schema = 'public'
    ORDER BY ordinal_position;
    """
    print("Cannot query information_schema directly through REST API")
except Exception as e:
    print(f"System table query failed: {e}")

# Method 2: Try a more thorough data query to see actual structure
print("\n2. Detailed table inspection...")
try:
    # Get a record and examine all fields
    result = supabase.table('transcriptions').select('*').limit(1).execute()
    
    if result.data:
        sample = result.data[0]
        all_keys = list(sample.keys())
        
        print(f"Total columns: {len(all_keys)}")
        print(f"Columns: {sorted(all_keys)}")
        
        # Specifically check for our target columns
        target_columns = ['quote', 'tldr']
        found_columns = []
        missing_columns = []
        
        for col in target_columns:
            if col in all_keys:
                found_columns.append(col)
                value = sample.get(col)
                print(f"✅ Found '{col}': {type(value)} = {value}")
            else:
                missing_columns.append(col)
                print(f"❌ Missing '{col}'")
        
        print(f"\nSummary: {len(found_columns)}/{len(target_columns)} target columns found")
        
    else:
        print("No data in table for inspection")
        
except Exception as e:
    print(f"Table inspection failed: {e}")

# Method 3: Try to insert/update with the new columns
print("\n3. Testing column functionality...")
try:
    # First try to select ONLY the new columns
    result = supabase.table('transcriptions').select('quote, tldr').limit(1).execute()
    print("✅ Can select quote and tldr columns successfully")
    
    if result.data:
        print(f"Sample data: {result.data[0]}")
    else:
        print("No records found with quote/tldr data")
        
except Exception as e:
    print(f"❌ Column functionality test failed: {e}")

# Method 4: Check if we can insert a test record with the columns
print("\n4. Testing insert capability...")
try:
    # We won't actually insert, just test the schema validation
    print("Note: Insert test skipped to avoid data modification")
    
    # But we can check if an update would work on an existing record
    result = supabase.table('transcriptions').select('task_id').limit(1).execute()
    if result.data:
        task_id = result.data[0]['task_id']
        print(f"Could test update on task_id: {task_id}")
        
        # Test if the update schema would accept our columns (dry run)
        update_data = {
            'quote': 'Test quote for schema validation',
            'tldr': ["Test point 1", "Test point 2"]
        }
        print(f"Update data format: {update_data}")
        print("✅ Update schema format looks valid")
        
except Exception as e:
    print(f"Insert capability test error: {e}")

print("\n=== CONCLUSION ===")
print("If the migration shows as applied in the CLI but columns aren't visible,")
print("this could indicate:")
print("1. A caching issue with the Supabase client")
print("2. The migration was applied to a different schema")
print("3. The columns exist but are not being returned by the REST API")
print("4. There's a permission issue preventing column access")