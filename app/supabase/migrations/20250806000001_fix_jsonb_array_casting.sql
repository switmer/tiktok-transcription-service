-- Fix JSONB to text[] casting in update_transcription function
-- The issue: '[...]'::jsonb::text[] doesn't work in PostgreSQL
-- Solution: Use array(select jsonb_array_elements_text(...))

DROP FUNCTION IF EXISTS public.update_transcription(uuid, jsonb);

CREATE OR REPLACE FUNCTION public.update_transcription(
  p_task_id UUID,
  p_update_data JSONB
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  result JSONB;
  update_columns TEXT[];
  update_values TEXT[];
  update_sql TEXT;
  i INTEGER;
BEGIN
  -- Extract keys and values from the update_data
  SELECT 
    array_agg(key),
    array_agg(CASE 
      WHEN value = 'null'::jsonb THEN NULL
      ELSE value #>> '{}'
    END)
  INTO 
    update_columns,
    update_values
  FROM jsonb_each(p_update_data);
  
  -- Build dynamic SQL for the update
  update_sql := 'UPDATE public.transcriptions SET ';
  
  -- Add each column=value pair
  FOR i IN 1..array_length(update_columns, 1) LOOP
    
    IF update_values[i] IS NULL THEN
      update_sql := update_sql || quote_ident(update_columns[i]) || ' = NULL';
    ELSIF update_columns[i] = 'tldr' THEN
      -- Handle JSONB columns - tldr is stored as JSON string
      update_sql := update_sql || quote_ident(update_columns[i]) || ' = ' || quote_literal(update_values[i]);
    ELSIF update_columns[i] = 'tags' OR update_columns[i] = 'auto_tags' THEN
      -- Handle array columns - convert JSON array to PostgreSQL text array
      -- Use array(select jsonb_array_elements_text(...)) for proper conversion
      update_sql := update_sql || quote_ident(update_columns[i]) || ' = array(select jsonb_array_elements_text(' || quote_literal(update_values[i]) || '::jsonb))';
    ELSIF update_columns[i] IN ('view_count', 'like_count', 'comment_count', 'repost_count', 'duration') THEN
      -- Handle integer columns
      IF update_values[i] ~ '^[0-9]+$' THEN
        update_sql := update_sql || quote_ident(update_columns[i]) || ' = ' || update_values[i] || '::bigint';
      ELSE
        update_sql := update_sql || quote_ident(update_columns[i]) || ' = NULL';
      END IF;
    ELSIF update_columns[i] = 'raw_metadata' THEN
      -- Handle raw_metadata JSONB column
      update_sql := update_sql || quote_ident(update_columns[i]) || ' = ' || quote_literal(update_values[i]) || '::jsonb';
    ELSE
      -- Handle regular text/varchar columns
      update_sql := update_sql || quote_ident(update_columns[i]) || ' = ' || quote_literal(update_values[i]);
    END IF;
    
    IF i < array_length(update_columns, 1) THEN
      update_sql := update_sql || ', ';
    END IF;
  END LOOP;
  
  -- Add updated_at timestamp
  update_sql := update_sql || ', updated_at = CURRENT_TIMESTAMP';
  
  -- Add the WHERE clause
  update_sql := update_sql || ' WHERE task_id = $1 RETURNING to_jsonb(transcriptions.*)';
  
  -- Log the SQL for debugging (comment out in production if needed)
  RAISE NOTICE 'Executing SQL: %', update_sql;
  
  -- Execute the dynamic SQL
  EXECUTE update_sql INTO result USING p_task_id;
  
  -- Return the updated record
  RETURN result;
END;
$$;

-- Grant execute permission to authenticated users and service role
GRANT EXECUTE ON FUNCTION public.update_transcription(UUID, JSONB) TO authenticated;
GRANT EXECUTE ON FUNCTION public.update_transcription(UUID, JSONB) TO service_role;
GRANT EXECUTE ON FUNCTION public.update_transcription(UUID, JSONB) TO anon;

-- Add comment for documentation
COMMENT ON FUNCTION public.update_transcription(UUID, JSONB) IS 
'Safely updates transcription records by bypassing PostGREST ON CONFLICT issues. 
Properly handles JSONB array to text[] conversion for tags/auto_tags columns.
Used by Edge Functions to handle problematic updates.';

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ update_transcription function fixed with proper JSONB array casting!';
    RAISE NOTICE 'Tags and auto_tags arrays will now be properly converted from JSON to PostgreSQL text arrays.';
END $$;

