-- Fix the PostgreSQL function to handle Python data types correctly

CREATE OR REPLACE FUNCTION update_transcription(
  p_task_id UUID,
  p_update_data JSONB
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  result JSONB;
  update_columns TEXT[];
  update_values TEXT[];
  update_sql TEXT;
  i INTEGER;
  current_value JSONB;
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
    -- Get the raw JSONB value for special handling
    current_value := p_update_data -> update_columns[i];
    
    -- Handle different data types appropriately
    IF update_values[i] IS NULL THEN
      update_sql := update_sql || quote_ident(update_columns[i]) || ' = NULL';
    ELSIF update_columns[i] = 'tldr' THEN
      -- Handle JSONB columns - tldr is stored as JSON string
      update_sql := update_sql || quote_ident(update_columns[i]) || ' = ' || quote_literal(update_values[i]);
    ELSIF update_columns[i] = 'tags' OR update_columns[i] = 'auto_tags' THEN
      -- Handle array columns - convert JSONB array to PostgreSQL text array
      IF jsonb_typeof(current_value) = 'array' THEN
        update_sql := update_sql || quote_ident(update_columns[i]) || ' = ARRAY(SELECT jsonb_array_elements_text(' || quote_literal(current_value::text) || '::jsonb))';
      ELSE
        -- Fallback for non-array values
        update_sql := update_sql || quote_ident(update_columns[i]) || ' = ARRAY[' || quote_literal(update_values[i]) || ']';
      END IF;
    ELSIF update_columns[i] IN ('view_count', 'like_count', 'comment_count', 'repost_count', 'duration') THEN
      -- Handle integer columns
      IF update_values[i] ~ '^[0-9]+$' THEN
        update_sql := update_sql || quote_ident(update_columns[i]) || ' = ' || update_values[i] || '::bigint';
      ELSE
        update_sql := update_sql || quote_ident(update_columns[i]) || ' = NULL';
      END IF;
    ELSIF update_columns[i] = 'raw_metadata' THEN
      -- Handle JSONB columns - store as JSONB
      update_sql := update_sql || quote_ident(update_columns[i]) || ' = ' || quote_literal(current_value::text) || '::jsonb';
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
  
  -- Log the SQL for debugging
  RAISE NOTICE 'Executing SQL: %', update_sql;
  
  -- Execute the dynamic SQL
  EXECUTE update_sql INTO result USING p_task_id;
  
  -- Return the updated record
  RETURN result;
END;
$$;