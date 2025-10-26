-- Fix Supabase Storage policies for complete thumbnail management
-- This addresses the missing UPDATE/DELETE policies identified in the architectural review

-- 1. ENSURE ASSETS BUCKET EXISTS
INSERT INTO storage.buckets (id, name, public) 
VALUES ('assets', 'assets', true)
ON CONFLICT (id) DO NOTHING;

-- 2. DROP EXISTING POLICIES (to recreate them properly)
DROP POLICY IF EXISTS "Public thumbnail access" ON storage.objects;
DROP POLICY IF EXISTS "Service role upload" ON storage.objects;
DROP POLICY IF EXISTS "Service role update" ON storage.objects;
DROP POLICY IF EXISTS "Service role delete" ON storage.objects;
DROP POLICY IF EXISTS "Service role manage" ON storage.objects;

-- 3. CREATE COMPREHENSIVE STORAGE POLICIES

-- Policy 1: Public read access to assets bucket
CREATE POLICY "Public thumbnail access" ON storage.objects
FOR SELECT USING (bucket_id = 'assets');

-- Policy 2: Service role can upload to assets bucket
CREATE POLICY "Service role upload" ON storage.objects
FOR INSERT WITH CHECK (
    bucket_id = 'assets' 
    AND auth.role() = 'service_role'
);

-- Policy 3: Service role can update existing objects in assets bucket
CREATE POLICY "Service role update" ON storage.objects
FOR UPDATE USING (
    bucket_id = 'assets' 
    AND auth.role() = 'service_role'
);

-- Policy 4: Service role can delete objects from assets bucket
CREATE POLICY "Service role delete" ON storage.objects
FOR DELETE USING (
    bucket_id = 'assets' 
    AND auth.role() = 'service_role'
);

-- Policy 5: Authenticated users can view their own objects (future feature)
CREATE POLICY "Authenticated user access" ON storage.objects
FOR SELECT USING (
    bucket_id = 'assets' 
    AND auth.role() = 'authenticated'
    -- Future: AND metadata->>'user_id' = auth.uid()::text
);

-- 4. GRANT NECESSARY PERMISSIONS
-- Ensure storage schema permissions are correct
GRANT USAGE ON SCHEMA storage TO authenticated, anon, service_role;
GRANT ALL ON storage.objects TO service_role;
GRANT SELECT ON storage.objects TO authenticated, anon;

-- 5. SET BUCKET CONFIGURATION
-- Update bucket settings for optimal performance
UPDATE storage.buckets 
SET 
    file_size_limit = 52428800,  -- 50MB limit
    allowed_mime_types = ARRAY['image/jpeg', 'image/png', 'image/webp', 'image/gif']::text[]
WHERE id = 'assets';

-- 6. CREATE STORAGE HELPER FUNCTIONS

-- Function to get storage usage for monitoring
CREATE OR REPLACE FUNCTION get_storage_usage()
RETURNS TABLE(
    bucket_id text,
    total_objects bigint,
    total_size_mb numeric
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        so.bucket_id,
        COUNT(*)::bigint as total_objects,
        ROUND(SUM(so.metadata->>'size')::numeric / 1024 / 1024, 2) as total_size_mb
    FROM storage.objects so
    WHERE so.bucket_id = 'assets'
    GROUP BY so.bucket_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to cleanup orphaned storage objects
CREATE OR REPLACE FUNCTION cleanup_orphaned_storage()
RETURNS TABLE(deleted_path text) AS $$
BEGIN
    RETURN QUERY
    WITH orphaned_objects AS (
        SELECT so.name, so.bucket_id
        FROM storage.objects so
        WHERE so.bucket_id = 'assets'
        AND so.name LIKE 'thumbnails/%'
        AND NOT EXISTS (
            SELECT 1 FROM transcriptions t 
            WHERE t.supabase_thumbnail_url LIKE '%' || so.name || '%'
            OR t.square_thumbnail_url LIKE '%' || so.name || '%'
        )
        -- Only delete objects older than 7 days to be safe
        AND so.created_at < NOW() - INTERVAL '7 days'
    )
    DELETE FROM storage.objects
    WHERE (name, bucket_id) IN (SELECT name, bucket_id FROM orphaned_objects)
    RETURNING name;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to validate storage object access
CREATE OR REPLACE FUNCTION validate_storage_access(object_path text)
RETURNS boolean AS $$
BEGIN
    -- Check if object exists and is accessible
    RETURN EXISTS (
        SELECT 1 FROM storage.objects 
        WHERE bucket_id = 'assets' 
        AND name = object_path
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 7. CREATE STORAGE MONITORING VIEW
CREATE OR REPLACE VIEW storage_health AS
SELECT 
    'assets'::text as bucket_name,
    COUNT(*) as total_thumbnails,
    COUNT(*) FILTER (WHERE name LIKE '%_square.%') as square_thumbnails,
    ROUND(AVG((metadata->>'size')::numeric) / 1024, 2) as avg_size_kb,
    ROUND(SUM((metadata->>'size')::numeric) / 1024 / 1024, 2) as total_size_mb,
    MIN(created_at) as oldest_object,
    MAX(created_at) as newest_object
FROM storage.objects 
WHERE bucket_id = 'assets';

-- Grant access to monitoring view
GRANT SELECT ON storage_health TO service_role;

-- 8. ADD STORAGE VALIDATION TO TRANSCRIPTIONS TABLE

-- Add function to validate thumbnail URLs point to our storage
CREATE OR REPLACE FUNCTION validate_thumbnail_storage_url(url text)
RETURNS boolean AS $$
BEGIN
    -- Allow null values
    IF url IS NULL THEN
        RETURN true;
    END IF;
    
    -- Must be a supabase storage URL for our project
    RETURN url LIKE '%supabase.co/storage/v1/object/public/assets/thumbnails/%';
END;
$$ LANGUAGE plpgsql;

-- Add constraints for thumbnail URL validation (initially not enforced)
-- These can be enabled later once all existing data is migrated
-- ALTER TABLE transcriptions 
-- ADD CONSTRAINT chk_supabase_thumbnail_url_valid 
-- CHECK (validate_thumbnail_storage_url(supabase_thumbnail_url));

-- ALTER TABLE transcriptions 
-- ADD CONSTRAINT chk_square_thumbnail_url_valid 
-- CHECK (validate_thumbnail_storage_url(square_thumbnail_url));

-- 9. COMMENTS FOR DOCUMENTATION
COMMENT ON POLICY "Public thumbnail access" ON storage.objects IS 'Allows public read access to thumbnail images in assets bucket';
COMMENT ON POLICY "Service role upload" ON storage.objects IS 'Allows service role to upload new thumbnail images';
COMMENT ON POLICY "Service role update" ON storage.objects IS 'Allows service role to update existing thumbnail images';
COMMENT ON POLICY "Service role delete" ON storage.objects IS 'Allows service role to delete orphaned thumbnail images';

COMMENT ON FUNCTION get_storage_usage() IS 'Returns storage usage statistics for monitoring';
COMMENT ON FUNCTION cleanup_orphaned_storage() IS 'Removes storage objects not referenced by any transcription record';
COMMENT ON FUNCTION validate_storage_access(text) IS 'Validates that a storage object path exists and is accessible';

-- Success message
DO $$
BEGIN
    RAISE NOTICE 'Storage policies and helper functions successfully created!';
    RAISE NOTICE 'Bucket: assets, Policies: 5, Helper functions: 3';
    RAISE NOTICE 'Storage is now ready for complete thumbnail management lifecycle.';
END $$;