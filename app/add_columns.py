#!/usr/bin/env python3
"""
Add quote and tldr columns using direct psycopg2
"""
import os
import psycopg2
from urllib.parse import urlparse

# Get database URL from environment
db_url = os.getenv('DATABASE_URL') or os.getenv('SUPABASE_DB_URL')

if not db_url:
    print("❌ No DATABASE_URL found. Please run this SQL manually in Supabase dashboard:")
    print("""
ALTER TABLE public.transcriptions 
ADD COLUMN IF NOT EXISTS quote text NULL,
ADD COLUMN IF NOT EXISTS tldr jsonb NULL;
""")
    exit(1)

try:
    # Parse the database URL
    parsed = urlparse(db_url)
    
    # Connect to the database
    conn = psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port,
        database=parsed.path[1:],  # Remove leading slash
        user=parsed.username,
        password=parsed.password
    )
    
    cur = conn.cursor()
    
    # Add the columns
    cur.execute("ALTER TABLE public.transcriptions ADD COLUMN IF NOT EXISTS quote text NULL;")
    cur.execute("ALTER TABLE public.transcriptions ADD COLUMN IF NOT EXISTS tldr jsonb NULL;")
    
    # Commit the changes
    conn.commit()
    
    print("✅ Successfully added quote and tldr columns!")
    
    # Close connections
    cur.close()
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")
    print("\nPlease run this SQL manually in your Supabase dashboard:")
    print("""
ALTER TABLE public.transcriptions 
ADD COLUMN IF NOT EXISTS quote text NULL,
ADD COLUMN IF NOT EXISTS tldr jsonb NULL;
""")