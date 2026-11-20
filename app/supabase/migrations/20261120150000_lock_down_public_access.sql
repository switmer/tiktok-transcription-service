-- Lock down public-schema access.
--
-- DO NOT APPLY THIS TO PRODUCTION (project eoktsarockavjdsxqhjm) without
-- Steve's explicit yes. Prefer a Supabase branch dry run first.
-- This file only describes the change. It was not executed against production.
--
-- Who connects today:
--   * FastAPI (app/database.py) uses SUPABASE_SERVICE_KEY. service_role
--     bypasses RLS and keeps EXECUTE plus full table grants.
--   * Edge functions sms-inbound, sms-status-callback, update-transcription,
--     and twilio-error-webhook create a client with SUPABASE_SERVICE_ROLE_KEY.
--   * transcribe-proxy does not query Postgres. It forwards to FastAPI
--     with the server-side API_KEY.
--   * The web client uses the anon key and Supabase Auth (email/password in
--     the switmer/ScribeTok copy). It reads and writes its own profiles and
--     transcriptions rows. It does not call credit, OTP, or admin RPCs.
--
-- After this migration:
--   * anon can SELECT the public_transcriptions view (completed + public,
--     no phone, user id, callback, or file path) and nothing else.
--   * authenticated can touch only rows linked to auth.uid(), the JWT phone,
--     or the JWT email on sms_users.
--   * TRUNCATE is revoked from anon and authenticated on every public table.
--   * SECURITY DEFINER functions get search_path = public and are executable
--     by service_role only, except the two helpers below.

-- ---------------------------------------------------------------------------
-- Helpers. SECURITY DEFINER so policies can resolve the caller's phones
-- without depending on the caller's visibility of otp columns.
-- They take no user id argument; identity comes only from the JWT.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.current_user_phones()
RETURNS SETOF text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT s.phone_number
  FROM public.sms_users AS s
  WHERE s.auth_user_id = (SELECT auth.uid())
     OR s.id = (SELECT auth.uid())
     OR (
       NULLIF(btrim((SELECT auth.jwt() ->> 'phone')), '') IS NOT NULL
       AND s.phone_number = (SELECT auth.jwt() ->> 'phone')
     )
     OR (
       NULLIF(btrim((SELECT auth.jwt() ->> 'email')), '') IS NOT NULL
       AND s.email IS NOT NULL
       AND lower(s.email) = lower((SELECT auth.jwt() ->> 'email'))
     );
$$;

CREATE OR REPLACE FUNCTION public.owns_phone(p_phone text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT p_phone IS NOT NULL
     AND length(btrim(p_phone)) > 0
     AND p_phone IN (SELECT public.current_user_phones());
$$;

REVOKE ALL ON FUNCTION public.current_user_phones() FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.owns_phone(text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.current_user_phones() TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.owns_phone(text) TO authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Drop policies that are true for anon/authenticated. service_role-only
-- policies are kept. Named policies we replace are dropped explicitly.
-- ---------------------------------------------------------------------------

DO $drop_open_policies$
DECLARE
  pol record;
BEGIN
  FOR pol IN
    SELECT schemaname, tablename, policyname
    FROM pg_policies
    WHERE schemaname = 'public'
      AND permissive = 'PERMISSIVE'
      AND (
        regexp_replace(COALESCE(qual, ''), '\s', '', 'g') IN ('true', '(true)')
        OR regexp_replace(COALESCE(with_check, ''), '\s', '', 'g') IN ('true', '(true)')
      )
      AND roles::text[] && ARRAY['public', 'anon', 'authenticated']::text[]
      AND NOT (roles::text[] <@ ARRAY['service_role']::text[])
  LOOP
    EXECUTE format(
      'DROP POLICY IF EXISTS %I ON %I.%I',
      pol.policyname, pol.schemaname, pol.tablename
    );
  END LOOP;
END
$drop_open_policies$;

DROP POLICY IF EXISTS "Public can view all transcriptions" ON public.transcriptions;
DROP POLICY IF EXISTS "Public can view completed public transcriptions" ON public.transcriptions;
DROP POLICY IF EXISTS "Users can view public or own transcriptions" ON public.transcriptions;
DROP POLICY IF EXISTS "search_public_completed" ON public.transcriptions;
DROP POLICY IF EXISTS "Users can view own transcriptions" ON public.transcriptions;
DROP POLICY IF EXISTS "Users can insert own transcriptions" ON public.transcriptions;
DROP POLICY IF EXISTS "Users can update own transcriptions" ON public.transcriptions;
DROP POLICY IF EXISTS "Users can delete own transcriptions" ON public.transcriptions;
DROP POLICY IF EXISTS "Users can view own record" ON public.sms_users;
DROP POLICY IF EXISTS "Users can update own record" ON public.sms_users;
DROP POLICY IF EXISTS "Users can view own credit transactions" ON public.credit_transactions;
DROP POLICY IF EXISTS "Users can view their own video stats" ON public.user_video_stats;
DROP POLICY IF EXISTS "Allow public read" ON public.video_comments;
DROP POLICY IF EXISTS "Allow public read" ON public.comments_fetch_progress;

-- ---------------------------------------------------------------------------
-- Enable RLS, take anon/authenticated grants off every table, and give
-- service_role an explicit policy so access does not depend on BYPASSRLS.
-- service_role's existing grants are re-applied at the end of this block.
-- ---------------------------------------------------------------------------

DO $lock_tables$
DECLARE
  rel record;
BEGIN
  FOR rel IN
    SELECT c.relname
    FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', rel.relname);
    EXECUTE format(
      'REVOKE ALL ON TABLE public.%I FROM PUBLIC, anon, authenticated',
      rel.relname
    );
    EXECUTE format(
      'DROP POLICY IF EXISTS rls_service_role_all ON public.%I',
      rel.relname
    );
    EXECUTE format(
      'CREATE POLICY rls_service_role_all ON public.%I FOR ALL TO service_role USING (true) WITH CHECK (true)',
      rel.relname
    );
  END LOOP;
END
$lock_tables$;

REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, anon, authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated;

-- ---------------------------------------------------------------------------
-- Own-row policies. authenticated only. anon has no policies on base tables.
-- ---------------------------------------------------------------------------

DROP POLICY IF EXISTS rls_transcriptions_select_own ON public.transcriptions;
CREATE POLICY rls_transcriptions_select_own
  ON public.transcriptions
  FOR SELECT
  TO authenticated
  USING (
    user_id = (SELECT auth.uid())
    OR public.owns_phone(user_phone)
  );

DROP POLICY IF EXISTS rls_transcriptions_insert_own ON public.transcriptions;
CREATE POLICY rls_transcriptions_insert_own
  ON public.transcriptions
  FOR INSERT
  TO authenticated
  WITH CHECK (
    user_id = (SELECT auth.uid())
    AND (user_phone IS NULL OR public.owns_phone(user_phone))
  );

DROP POLICY IF EXISTS rls_transcriptions_update_own ON public.transcriptions;
CREATE POLICY rls_transcriptions_update_own
  ON public.transcriptions
  FOR UPDATE
  TO authenticated
  USING (
    user_id = (SELECT auth.uid())
    OR public.owns_phone(user_phone)
  )
  WITH CHECK (
    (user_id IS NULL OR user_id = (SELECT auth.uid()))
    AND (user_phone IS NULL OR public.owns_phone(user_phone))
  );

DROP POLICY IF EXISTS rls_transcriptions_delete_own ON public.transcriptions;
CREATE POLICY rls_transcriptions_delete_own
  ON public.transcriptions
  FOR DELETE
  TO authenticated
  USING (
    user_id = (SELECT auth.uid())
    OR public.owns_phone(user_phone)
  );

GRANT SELECT, INSERT, UPDATE, DELETE ON public.transcriptions TO authenticated;

DROP POLICY IF EXISTS rls_sms_users_select_own ON public.sms_users;
CREATE POLICY rls_sms_users_select_own
  ON public.sms_users
  FOR SELECT
  TO authenticated
  USING (public.owns_phone(phone_number));

-- Column list excludes OTP, verification, and session secrets. select('*')
-- from the browser fails on purpose; request the columns the screen needs.
DO $sms_user_columns$
DECLARE
  cols text;
  secret_columns text[] := ARRAY[
    'verification_code',
    'verification_expires',
    'session_token',
    'session_expires',
    'otp_hash',
    'otp_nonce',
    'otp_attempts',
    'otp_locked_until',
    'otp_send_count',
    'otp_send_window_start'
  ];
BEGIN
  SELECT string_agg(format('%I', column_name), ', ' ORDER BY ordinal_position)
    INTO cols
  FROM information_schema.columns
  WHERE table_schema = 'public'
    AND table_name = 'sms_users'
    AND column_name <> ALL (secret_columns);

  IF cols IS NULL THEN
    RAISE EXCEPTION 'sms_users has no non-secret columns to grant';
  END IF;

  EXECUTE 'REVOKE ALL ON TABLE public.sms_users FROM PUBLIC, anon, authenticated';
  EXECUTE format('GRANT SELECT (%s) ON TABLE public.sms_users TO authenticated', cols);
  EXECUTE 'GRANT ALL ON TABLE public.sms_users TO service_role';
END
$sms_user_columns$;

DROP POLICY IF EXISTS rls_user_messages_select_own ON public.user_messages;
CREATE POLICY rls_user_messages_select_own
  ON public.user_messages
  FOR SELECT
  TO authenticated
  USING (
    public.owns_phone(from_phone)
    OR public.owns_phone(to_phone)
  );

GRANT SELECT ON public.user_messages TO authenticated;

DROP POLICY IF EXISTS rls_referrals_select_own ON public.referrals;
CREATE POLICY rls_referrals_select_own
  ON public.referrals
  FOR SELECT
  TO authenticated
  USING (
    public.owns_phone(referrer_phone)
    OR public.owns_phone(referee_phone)
  );

GRANT SELECT ON public.referrals TO authenticated;

DROP POLICY IF EXISTS rls_user_video_stats_select_own ON public.user_video_stats;
CREATE POLICY rls_user_video_stats_select_own
  ON public.user_video_stats
  FOR SELECT
  TO authenticated
  USING (public.owns_phone(user_phone));

GRANT SELECT ON public.user_video_stats TO authenticated;

DROP POLICY IF EXISTS rls_tiktok_profile_stats_select_own ON public.tiktok_profile_stats;
CREATE POLICY rls_tiktok_profile_stats_select_own
  ON public.tiktok_profile_stats
  FOR SELECT
  TO authenticated
  USING (
    tiktok_handle IS NOT NULL
    AND tiktok_handle IN (
      SELECT s.tiktok_handle
      FROM public.sms_users AS s
      WHERE public.owns_phone(s.phone_number)
        AND s.tiktok_handle IS NOT NULL
    )
  );

GRANT SELECT ON public.tiktok_profile_stats TO authenticated;

DROP POLICY IF EXISTS rls_credit_transactions_select_own ON public.credit_transactions;
CREATE POLICY rls_credit_transactions_select_own
  ON public.credit_transactions
  FOR SELECT
  TO authenticated
  USING (public.owns_phone(user_phone));

GRANT SELECT ON public.credit_transactions TO authenticated;

-- Replaces the app.current_user_phone setting, which any SQL session can SET.
-- The email policy on credit_purchases stays; this adds the phone link.
DROP POLICY IF EXISTS rls_credit_purchases_select_own_phone ON public.credit_purchases;
CREATE POLICY rls_credit_purchases_select_own_phone
  ON public.credit_purchases
  FOR SELECT
  TO authenticated
  USING (public.owns_phone(phone_number));

GRANT SELECT ON public.credit_purchases TO authenticated;

DROP POLICY IF EXISTS rls_conversation_threads_own ON public.conversation_threads;
CREATE POLICY rls_conversation_threads_own
  ON public.conversation_threads
  FOR ALL
  TO authenticated
  USING (public.owns_phone(user_phone))
  WITH CHECK (public.owns_phone(user_phone));

GRANT SELECT, INSERT, UPDATE, DELETE ON public.conversation_threads TO authenticated;

DROP POLICY IF EXISTS rls_conversation_messages_select_own ON public.conversation_messages;
CREATE POLICY rls_conversation_messages_select_own
  ON public.conversation_messages
  FOR SELECT
  TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.conversation_threads AS t
      WHERE t.id = conversation_messages.thread_id
        AND public.owns_phone(t.user_phone)
    )
  );

DROP POLICY IF EXISTS rls_conversation_messages_insert_own ON public.conversation_messages;
CREATE POLICY rls_conversation_messages_insert_own
  ON public.conversation_messages
  FOR INSERT
  TO authenticated
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM public.conversation_threads AS t
      WHERE t.id = thread_id
        AND public.owns_phone(t.user_phone)
    )
  );

GRANT SELECT, INSERT ON public.conversation_messages TO authenticated;

DROP POLICY IF EXISTS rls_video_comments_select_own ON public.video_comments;
CREATE POLICY rls_video_comments_select_own
  ON public.video_comments
  FOR SELECT
  TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.transcriptions AS t
      WHERE t.task_id = video_comments.task_id
        AND (
          t.user_id = (SELECT auth.uid())
          OR public.owns_phone(t.user_phone)
        )
    )
  );

GRANT SELECT ON public.video_comments TO authenticated;

DROP POLICY IF EXISTS rls_comments_progress_select_own ON public.comments_fetch_progress;
CREATE POLICY rls_comments_progress_select_own
  ON public.comments_fetch_progress
  FOR SELECT
  TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.transcriptions AS t
      WHERE t.task_id = comments_fetch_progress.task_id
        AND (
          t.user_id = (SELECT auth.uid())
          OR public.owns_phone(t.user_phone)
        )
    )
  );

GRANT SELECT ON public.comments_fetch_progress TO authenticated;

-- profiles and schema_cache exist in production and are not created by the
-- earlier migrations, so they are conditional.
DO $profiles$
BEGIN
  IF to_regclass('public.profiles') IS NULL THEN
    RETURN;
  END IF;

  EXECUTE 'ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY';
  EXECUTE 'REVOKE ALL ON TABLE public.profiles FROM PUBLIC, anon, authenticated';
  EXECUTE 'GRANT ALL ON TABLE public.profiles TO service_role';
  EXECUTE 'DROP POLICY IF EXISTS rls_service_role_all ON public.profiles';
  EXECUTE 'CREATE POLICY rls_service_role_all ON public.profiles FOR ALL TO service_role USING (true) WITH CHECK (true)';
  EXECUTE 'DROP POLICY IF EXISTS rls_profiles_select_own ON public.profiles';
  EXECUTE $policy$
    CREATE POLICY rls_profiles_select_own
      ON public.profiles
      FOR SELECT
      TO authenticated
      USING (id = (SELECT auth.uid()))
  $policy$;
  EXECUTE 'DROP POLICY IF EXISTS rls_profiles_insert_own ON public.profiles';
  EXECUTE $policy$
    CREATE POLICY rls_profiles_insert_own
      ON public.profiles
      FOR INSERT
      TO authenticated
      WITH CHECK (
        id = (SELECT auth.uid())
        AND lower(email) = lower((SELECT auth.jwt() ->> 'email'))
        AND (credits IS NULL OR credits = 0)
      )
  $policy$;
  EXECUTE 'DROP POLICY IF EXISTS rls_profiles_update_own ON public.profiles';
  EXECUTE $policy$
    CREATE POLICY rls_profiles_update_own
      ON public.profiles
      FOR UPDATE
      TO authenticated
      USING (id = (SELECT auth.uid()))
      WITH CHECK (
        id = (SELECT auth.uid())
        AND lower(email) = lower((SELECT auth.jwt() ->> 'email'))
      )
  $policy$;
  EXECUTE 'GRANT SELECT ON TABLE public.profiles TO authenticated';
  EXECUTE 'GRANT INSERT (id, email, created_at, updated_at) ON TABLE public.profiles TO authenticated';
  EXECUTE 'GRANT UPDATE (email, updated_at) ON TABLE public.profiles TO authenticated';
END
$profiles$;

DO $schema_cache$
BEGIN
  IF to_regclass('public.schema_cache') IS NULL THEN
    RETURN;
  END IF;

  EXECUTE 'ALTER TABLE public.schema_cache ENABLE ROW LEVEL SECURITY';
  EXECUTE 'REVOKE ALL ON TABLE public.schema_cache FROM PUBLIC, anon, authenticated';
  EXECUTE 'GRANT ALL ON TABLE public.schema_cache TO service_role';
  EXECUTE 'DROP POLICY IF EXISTS rls_service_role_all ON public.schema_cache';
  EXECUTE 'CREATE POLICY rls_service_role_all ON public.schema_cache FOR ALL TO service_role USING (true) WITH CHECK (true)';
END
$schema_cache$;

-- ---------------------------------------------------------------------------
-- Public projection. Runs as the view owner with security_barrier, so anon
-- never receives user_phone or file paths. security_invoker is intentionally
-- off: anon has no SELECT on the base table.
-- ---------------------------------------------------------------------------

DO $public_view$
DECLARE
  cols text;
  where_sql text;
  hidden_columns text[] := ARRAY[
    'user_id',
    'user_phone',
    'callback_url',
    'thumbnail_local_path',
    'transcript_file_path',
    'audio_file_path',
    'info_file_path',
    'metadata',
    'raw_metadata'
  ];
BEGIN
  IF to_regclass('public.transcriptions') IS NULL THEN
    RETURN;
  END IF;

  SELECT string_agg(format('t.%I', column_name), ', ' ORDER BY ordinal_position)
    INTO cols
  FROM information_schema.columns
  WHERE table_schema = 'public'
    AND table_name = 'transcriptions'
    AND column_name <> ALL (hidden_columns);

  IF cols IS NULL THEN
    RAISE EXCEPTION 'transcriptions has no public columns for public_transcriptions';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'transcriptions'
      AND column_name = 'visibility'
  ) THEN
    where_sql := 't.status = ''completed'' AND t.visibility::text = ''public''';
  ELSE
    where_sql := 't.status = ''completed''';
  END IF;

  EXECUTE 'DROP VIEW IF EXISTS public.public_transcriptions';
  EXECUTE format(
    'CREATE VIEW public.public_transcriptions WITH (security_barrier = true) AS SELECT %s FROM public.transcriptions AS t WHERE %s',
    cols,
    where_sql
  );
  EXECUTE $comment$
    COMMENT ON VIEW public.public_transcriptions IS
      'Completed public transcriptions for the anon key. Omits phone, user id, callback URL, metadata, and file paths.'
  $comment$;
  EXECUTE 'REVOKE ALL ON TABLE public.public_transcriptions FROM PUBLIC, anon, authenticated';
  EXECUTE 'GRANT SELECT ON TABLE public.public_transcriptions TO anon, authenticated, service_role';
END
$public_view$;

-- Every other public view (sms_job_status, storage_health, public_viral_stats)
-- includes phones or storage internals. Invoker mode plus no anon grant.
DO $lock_views$
DECLARE
  rel record;
BEGIN
  FOR rel IN
    SELECT c.relname
    FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'v'
      AND c.relname <> 'public_transcriptions'
  LOOP
    EXECUTE format(
      'REVOKE ALL ON TABLE public.%I FROM PUBLIC, anon, authenticated',
      rel.relname
    );
    EXECUTE format('GRANT SELECT ON TABLE public.%I TO service_role', rel.relname);
    EXECUTE format('ALTER VIEW public.%I SET (security_invoker = true)', rel.relname);
  END LOOP;
END
$lock_views$;

-- ---------------------------------------------------------------------------
-- Functions. Browser RPCs in the ScribeTok client: none.
-- service_role keeps EXECUTE. anon and authenticated lose it.
-- Trigger functions are left executable so authenticated writes still fire.
-- ---------------------------------------------------------------------------

DO $lock_functions$
DECLARE
  fn record;
  sensitive_names text[] := ARRAY[
    'request_otp',
    'verify_otp',
    'use_credit',
    'process_referral',
    'use_pending_referral',
    'update_referral_tracking',
    'safe_message_log',
    'get_user_referrals',
    'cleanup_expired_referrals',
    'cleanup_orphaned_referrals',
    'detect_sms_redundancies',
    'check_fk_integrity',
    'fts_health_check',
    'find_orphaned_thumbnails',
    'get_schema_columns_v1',
    'get_schema_functions_v1',
    'get_schema_tables_v1',
    'generate_referral_code',
    'search_content',
    'search_viral_quotes',
    'search_transcriptions',
    'decrement_credits',
    'exec_sql',
    'record_video_transcription',
    'atomic_deduct_credits'
  ];
BEGIN
  FOR fn IN
    SELECT p.oid::regprocedure AS signature
    FROM pg_proc AS p
    JOIN pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.prokind = 'f'
      AND p.prorettype <> 'trigger'::regtype
      AND p.proname NOT IN ('current_user_phones', 'owns_phone')
      AND (
        p.prosecdef
        OR p.proname = ANY (sensitive_names)
      )
  LOOP
    EXECUTE format(
      'REVOKE ALL ON FUNCTION %s FROM PUBLIC, anon, authenticated',
      fn.signature
    );
    EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', fn.signature);
    IF EXISTS (
      SELECT 1
      FROM pg_proc AS p
      WHERE p.oid::regprocedure = fn.signature
        AND p.prosecdef
    ) THEN
      EXECUTE format('ALTER FUNCTION %s SET search_path = public', fn.signature);
    END IF;
  END LOOP;
END
$lock_functions$;

-- Future tables created by postgres should not hand TRUNCATE to the browser roles.
DO $defaults$
BEGIN
  EXECUTE
    'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE TRUNCATE ON TABLES FROM PUBLIC, anon, authenticated';
EXCEPTION
  WHEN insufficient_privilege THEN
    RAISE NOTICE 'skipped default privilege change: %', SQLERRM;
END
$defaults$;
