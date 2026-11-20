-- Timed transcript segments for citation (YouTube captions and Whisper).
--
-- Adds nullable jsonb `transcriptions.segments`: a list of
-- {"start": <seconds>, "end": <seconds>, "text": "..."} or NULL when the
-- provider did not return timings.
--
-- Not applied by this change. Apply before deploying the code that selects
-- the column. Reads tolerate a missing column; the follow-up write does not
-- fail the transcript text update, but segments stay empty until this runs.
--
-- The completion path writes segments with the Supabase client, not
-- update_transcription(). That RPC stringifies unknown jsonb (see
-- 20250806000001_fix_jsonb_array_casting.sql), so this migration does not
-- replace it.
--
-- search_content / search_viral_quotes currently return every completed row.
-- This tightens them to public and legacy null visibility so a direct RPC
-- call cannot list private or unlisted tasks. search_transcriptions already
-- filters visibility = 'public' when only_public is true.
--
-- Rollback:
--   ALTER TABLE public.transcriptions DROP COLUMN IF EXISTS segments;
--   Restore search_content and search_viral_quotes from
--   20250722000028_add_production_fts.sql (bodies are unchanged after that
--   file except the visibility predicate added here).

ALTER TABLE public.transcriptions
    ADD COLUMN IF NOT EXISTS segments jsonb;

COMMENT ON COLUMN public.transcriptions.segments IS
    'Normalized timed segments [{start, end, text}] in seconds. NULL when timings were not available.';

CREATE OR REPLACE FUNCTION search_content(
    search_query text,
    limit_count integer DEFAULT 20,
    offset_count integer DEFAULT 0
)
RETURNS TABLE(
    task_id uuid,
    title text,
    quote text,
    tldr jsonb,
    platform text,
    like_count bigint,
    view_count bigint,
    created_at timestamptz,
    search_rank real
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        t.task_id,
        t.title,
        t.quote,
        t.tldr,
        t.platform,
        t.like_count,
        t.view_count,
        t.created_at,
        ts_rank(t.fts, plainto_tsquery('english', search_query)) as search_rank
    FROM transcriptions t
    WHERE t.status = 'completed'
      AND t.fts @@ plainto_tsquery('english', search_query)
      AND (t.visibility IS NULL OR t.visibility = 'public')
    ORDER BY search_rank DESC, t.like_count DESC NULLS LAST, t.created_at DESC
    LIMIT limit_count OFFSET offset_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION search_content IS
'FTS search across transcript/quote/tldr. Omits private and unlisted rows.';

CREATE OR REPLACE FUNCTION search_viral_quotes(
    search_query text,
    min_likes integer DEFAULT 10,
    limit_count integer DEFAULT 10
)
RETURNS TABLE(
    task_id uuid,
    quote text,
    title text,
    platform text,
    like_count bigint,
    search_rank real
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        t.task_id,
        t.quote,
        t.title,
        t.platform,
        t.like_count,
        ts_rank(t.fts, plainto_tsquery('english', search_query)) as search_rank
    FROM transcriptions t
    WHERE t.status = 'completed'
      AND t.quote IS NOT NULL
      AND t.like_count >= min_likes
      AND t.fts @@ plainto_tsquery('english', search_query)
      AND (t.visibility IS NULL OR t.visibility = 'public')
    ORDER BY search_rank DESC, t.like_count DESC
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION search_viral_quotes IS
'High-engagement quote search. Omits private and unlisted rows.';
