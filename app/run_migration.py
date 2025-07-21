#!/usr/bin/env python3
"""
Run the quote+TLDR migration manually
"""
import os
from database import supabase

def run_migration():
    """Add quote and tldr columns to transcriptions table"""
    
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
    
    try:
        result = supabase.rpc('exec_sql', {'sql': migration_sql})
        print("✅ Migration completed successfully!")
        print(f"Result: {result}")
    except Exception as e:
        # Try alternative approach with individual statements
        print(f"RPC failed: {e}")
        print("Trying alternative approach...")
        
        try:
            # Add columns
            supabase.rpc('exec_sql', {'sql': 'ALTER TABLE public.transcriptions ADD COLUMN IF NOT EXISTS quote text NULL'})
            supabase.rpc('exec_sql', {'sql': 'ALTER TABLE public.transcriptions ADD COLUMN IF NOT EXISTS tldr jsonb NULL'})
            print("✅ Columns added successfully!")
            
        except Exception as e2:
            print(f"❌ Migration failed: {e2}")
            print("You may need to run this SQL manually in the Supabase dashboard:")
            print(migration_sql)

if __name__ == "__main__":
    run_migration()