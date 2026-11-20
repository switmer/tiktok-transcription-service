-- Roll back 20261120150000_lock_down_public_access.sql.
--
-- This restores the previous grants and policies, including the open ones.
-- Run it only to undo that migration. Do not run it on its own against a
-- database that never received the lockdown.

-- ---------------------------------------------------------------------------
-- Drop lockdown policies and helper functions.
-- ---------------------------------------------------------------------------

DO $drop_lockdown_policies$
DECLARE
  pol record;
BEGIN
  FOR pol IN
    SELECT schemaname, tablename, policyname
    FROM pg_policies
    WHERE schemaname = 'public'
      AND policyname LIKE 'rls\_%' ESCAPE '\'
  LOOP
    EXECUTE format(
      'DROP POLICY IF EXISTS %I ON %I.%I',
      pol.policyname, pol.schemaname, pol.tablename
    );
  END LOOP;
END
$drop_lockdown_policies$;

DROP FUNCTION IF EXISTS public.owns_phone(text);
DROP FUNCTION IF EXISTS public.current_user_phones();

-- ---------------------------------------------------------------------------
-- Views. Clear invoker/barrier options, then restore the prior definitions
-- captured from production before the lockdown.
-- ---------------------------------------------------------------------------

DO $reset_view_options$
DECLARE
  rel record;
BEGIN
  FOR rel IN
    SELECT c.relname
    FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'v'
  LOOP
    BEGIN
      EXECUTE format('ALTER VIEW public.%I RESET (security_invoker)', rel.relname);
    EXCEPTION
      WHEN OTHERS THEN
        NULL;
    END;
  END LOOP;
END
$reset_view_options$;

DROP VIEW IF EXISTS public.public_transcriptions;
CREATE VIEW public.public_transcriptions AS
 SELECT transcriptions.task_id,
    transcriptions.user_id,
    transcriptions.url,
    transcriptions.status,
    transcriptions.created_at,
    transcriptions.updated_at,
    transcriptions.video_id,
    transcriptions.title,
    transcriptions.error,
    transcriptions.thumbnail_url,
    transcriptions.thumbnail_local_path,
    transcriptions.supabase_thumbnail_url,
    transcriptions.square_thumbnail_url,
    transcriptions.transcript_file_path,
    transcriptions.callback_url,
    transcriptions.visibility,
    transcriptions.tags,
    transcriptions.category,
    transcriptions.view_count,
    transcriptions.last_viewed_at,
    transcriptions.transcript,
    transcriptions.source,
    transcriptions.metadata,
    transcriptions.description,
    transcriptions.duration,
    transcriptions.upload_date,
    transcriptions."timestamp",
    transcriptions.channel,
    transcriptions.channel_id,
    transcriptions.uploader,
    transcriptions.uploader_url,
    transcriptions.like_count,
    transcriptions.comment_count,
    transcriptions.repost_count,
    transcriptions.resolution,
    transcriptions.width,
    transcriptions.height,
    transcriptions.aspect_ratio,
    transcriptions.filesize,
    transcriptions.format_id,
    transcriptions.vcodec,
    transcriptions.acodec,
    transcriptions.audio_file_path,
    transcriptions.info_file_path,
    transcriptions.auto_tags,
    transcriptions.content_category,
    transcriptions.language,
    transcriptions.platform,
    transcriptions.video_url,
    transcriptions.quote,
    transcriptions.tldr
   FROM transcriptions
  WHERE transcriptions.status = 'completed'::text
    AND transcriptions.visibility = 'public'::visibility_type;

DROP VIEW IF EXISTS public.sms_job_status;
CREATE VIEW public.sms_job_status AS
 SELECT t.task_id AS job_id,
    t.user_phone AS from_phone,
    t.url AS video_url,
    t.status AS transcription_status,
    t.created_at AS transcription_created,
    t.title,
    t.quote,
    t.error,
    CASE
      WHEN t.status = 'completed'::text THEN 'completed'::text
      WHEN t.status = 'failed'::text THEN 'failed'::text
      WHEN t.status = 'processing'::text THEN 'processing'::text
      ELSE 'pending'::text
    END AS unified_status
   FROM transcriptions t
  WHERE t.user_phone IS NOT NULL
    AND t.created_at >= (CURRENT_DATE - '7 days'::interval)
  ORDER BY t.created_at DESC;

DO $storage_health$
BEGIN
  IF to_regclass('storage.objects') IS NULL THEN
    RETURN;
  END IF;

  EXECUTE 'DROP VIEW IF EXISTS public.storage_health';
  EXECUTE $view$
    CREATE VIEW public.storage_health AS
     SELECT 'assets'::text AS bucket_name,
        count(*) AS total_thumbnails,
        count(*) FILTER (WHERE objects.name ~~ '%_square.%'::text) AS square_thumbnails,
        round(avg((objects.metadata ->> 'size'::text)::numeric) / 1024::numeric, 2) AS avg_size_kb,
        round(sum((objects.metadata ->> 'size'::text)::numeric) / 1024::numeric / 1024::numeric, 2) AS total_size_mb,
        min(objects.created_at) AS oldest_object,
        max(objects.created_at) AS newest_object
       FROM storage.objects
      WHERE objects.bucket_id = 'assets'::text
  $view$;
END
$storage_health$;

-- ---------------------------------------------------------------------------
-- RLS flags that were off in production before the lockdown.
-- Tables that already had RLS stay enabled.
-- ---------------------------------------------------------------------------

ALTER TABLE public.user_messages DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.referrals DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_video_stats DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.tiktok_profile_stats DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_threads DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_messages DISABLE ROW LEVEL SECURITY;

-- profiles and schema_cache exist in production. A database built only from
-- the repo migrations does not have them.
DO $optional_tables$
BEGIN
  IF to_regclass('public.profiles') IS NOT NULL THEN
    EXECUTE 'ALTER TABLE public.profiles DISABLE ROW LEVEL SECURITY';
  END IF;
  IF to_regclass('public.schema_cache') IS NOT NULL THEN
    EXECUTE 'ALTER TABLE public.schema_cache DISABLE ROW LEVEL SECURITY';
  END IF;
END
$optional_tables$;

-- ---------------------------------------------------------------------------
-- Policies that were dropped. Shapes match the production catalog.
-- ---------------------------------------------------------------------------

DROP POLICY IF EXISTS "Allow service role access" ON public.api_keys;
CREATE POLICY "Allow service role access"
  ON public.api_keys
  FOR ALL
  USING (true)
  WITH CHECK (true);

DROP POLICY IF EXISTS "Allow public read" ON public.comments_fetch_progress;
CREATE POLICY "Allow public read"
  ON public.comments_fetch_progress
  FOR SELECT
  USING (true);

DROP POLICY IF EXISTS "Allow public read" ON public.video_comments;
CREATE POLICY "Allow public read"
  ON public.video_comments
  FOR SELECT
  USING (true);

DROP POLICY IF EXISTS "Public can view all transcriptions" ON public.transcriptions;
CREATE POLICY "Public can view all transcriptions"
  ON public.transcriptions
  FOR SELECT
  USING (true);

DROP POLICY IF EXISTS "Public can view completed public transcriptions" ON public.transcriptions;
CREATE POLICY "Public can view completed public transcriptions"
  ON public.transcriptions
  FOR SELECT
  TO anon
  USING (
    status = 'completed'::text
    AND visibility = 'public'::visibility_type
  );

DROP POLICY IF EXISTS "Users can delete own transcriptions" ON public.transcriptions;
CREATE POLICY "Users can delete own transcriptions"
  ON public.transcriptions
  FOR DELETE
  USING (user_id = auth.uid());

DROP POLICY IF EXISTS "Users can insert own transcriptions" ON public.transcriptions;
CREATE POLICY "Users can insert own transcriptions"
  ON public.transcriptions
  FOR INSERT
  WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "Users can update own transcriptions" ON public.transcriptions;
CREATE POLICY "Users can update own transcriptions"
  ON public.transcriptions
  FOR UPDATE
  TO authenticated
  USING (
    user_id::text = (auth.uid())::text
    OR user_phone = (auth.jwt() ->> 'phone')
  );

DROP POLICY IF EXISTS "Users can view own transcriptions" ON public.transcriptions;
CREATE POLICY "Users can view own transcriptions"
  ON public.transcriptions
  FOR SELECT
  TO authenticated
  USING (
    user_id::text = (auth.uid())::text
    OR user_phone = (auth.jwt() ->> 'phone')
  );

DROP POLICY IF EXISTS "Users can view public or own transcriptions" ON public.transcriptions;
CREATE POLICY "Users can view public or own transcriptions"
  ON public.transcriptions
  FOR SELECT
  USING (
    visibility = 'public'::visibility_type
    OR user_id = auth.uid()
  );

DROP POLICY IF EXISTS search_public_completed ON public.transcriptions;
CREATE POLICY search_public_completed
  ON public.transcriptions
  FOR SELECT
  TO anon, authenticated
  USING (
    visibility = 'public'::visibility_type
    AND status = 'completed'::text
  );

DROP POLICY IF EXISTS "Users can view own record" ON public.sms_users;
CREATE POLICY "Users can view own record"
  ON public.sms_users
  FOR SELECT
  TO authenticated
  USING (
    (auth.jwt() ->> 'phone') = phone_number
    OR id::text = (auth.uid())::text
  );

DROP POLICY IF EXISTS "Users can update own record" ON public.sms_users;
CREATE POLICY "Users can update own record"
  ON public.sms_users
  FOR UPDATE
  TO authenticated
  USING (
    (auth.jwt() ->> 'phone') = phone_number
    OR id::text = (auth.uid())::text
  );

DROP POLICY IF EXISTS "Users can view own credit transactions" ON public.credit_transactions;
CREATE POLICY "Users can view own credit transactions"
  ON public.credit_transactions
  FOR SELECT
  USING (user_phone = current_setting('app.current_user_phone', true));

-- ---------------------------------------------------------------------------
-- Grants and function execution, back to the previous broad defaults.
-- fulfill_sms_credit_purchase was already service_role-only; keep it that way.
-- ---------------------------------------------------------------------------

GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;

DO $restore_functions$
DECLARE
  fn record;
BEGIN
  FOR fn IN
    SELECT p.oid::regprocedure AS signature, p.proname, p.prosecdef
    FROM pg_proc AS p
    JOIN pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.prokind = 'f'
      AND p.prorettype <> 'trigger'::regtype
  LOOP
    IF fn.proname = 'fulfill_sms_credit_purchase' THEN
      EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC, anon, authenticated', fn.signature);
      EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', fn.signature);
    ELSE
      EXECUTE format(
        'GRANT EXECUTE ON FUNCTION %s TO PUBLIC, anon, authenticated, service_role',
        fn.signature
      );
    END IF;

    IF fn.prosecdef AND fn.proname NOT IN ('fulfill_sms_credit_purchase', 'update_transcription') THEN
      EXECUTE format('ALTER FUNCTION %s RESET search_path', fn.signature);
    END IF;
  END LOOP;
END
$restore_functions$;
