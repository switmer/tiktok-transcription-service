-- Assertions for the lockdown migration. Fails the script on any miss.
-- Runs as the table owner. Each check switches role inside a function.

CREATE OR REPLACE FUNCTION public._assert_denied(role_name text, claims text, query text)
RETURNS void
LANGUAGE plpgsql
AS $fn$
BEGIN
  PERFORM set_config('request.jwt.claims', claims, true);
  EXECUTE format('SET LOCAL ROLE %I', role_name);
  EXECUTE query;
  RAISE EXCEPTION 'expected permission denial for % running %', role_name, query;
EXCEPTION
  WHEN insufficient_privilege THEN
    NULL;
END;
$fn$;

CREATE OR REPLACE FUNCTION public._assert_count(
  role_name text,
  claims text,
  query text,
  expected integer
)
RETURNS void
LANGUAGE plpgsql
AS $fn$
DECLARE
  found integer;
BEGIN
  PERFORM set_config('request.jwt.claims', claims, true);
  EXECUTE format('SET LOCAL ROLE %I', role_name);
  EXECUTE query INTO found;
  IF found IS DISTINCT FROM expected THEN
    RAISE EXCEPTION '% running % returned %, expected %', role_name, query, found, expected;
  END IF;
END;
$fn$;

SELECT public._assert_denied(
  'anon',
  '{"role":"anon"}',
  'SELECT count(*) FROM public.user_messages'
);

SELECT public._assert_denied(
  'anon',
  '{"role":"anon"}',
  'SELECT count(*) FROM public.api_keys'
);

SELECT public._assert_denied(
  'anon',
  '{"role":"anon"}',
  'SELECT count(*) FROM public.transcriptions'
);

SELECT public._assert_denied(
  'anon',
  '{"role":"anon"}',
  'SELECT count(*) FROM public.sms_users'
);

SELECT public._assert_denied(
  'anon',
  '{"role":"anon"}',
  'SELECT count(*) FROM public.schema_cache'
);

SELECT public._assert_denied(
  'anon',
  '{"role":"anon"}',
  'SELECT count(*) FROM public.sms_job_status'
);

SELECT public._assert_denied(
  'anon',
  '{"role":"anon"}',
  'TRUNCATE public.user_messages'
);

SELECT public._assert_denied(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  'TRUNCATE public.transcriptions'
);

SELECT public._assert_count(
  'anon',
  '{"role":"anon"}',
  'SELECT count(*) FROM public.public_transcriptions',
  1
);

DO $hidden_columns$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_attribute AS a
    JOIN pg_class AS c ON c.oid = a.attrelid
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'public_transcriptions'
      AND a.attname IN (
        'user_phone', 'user_id', 'callback_url', 'transcript_file_path',
        'audio_file_path', 'info_file_path', 'thumbnail_local_path',
        'metadata', 'raw_metadata'
      )
      AND a.attnum > 0
      AND NOT a.attisdropped
  ) THEN
    RAISE EXCEPTION 'public_transcriptions still exposes a private column';
  END IF;
END
$hidden_columns$;

SELECT public._assert_count(
  'anon',
  '{"role":"anon"}',
  $$SELECT count(*) FROM public.public_transcriptions WHERE title = 'Public completed'$$,
  1
);

SELECT public._assert_count(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  'SELECT count(*) FROM public.transcriptions',
  2
);

SELECT public._assert_count(
  'authenticated',
  '{"sub":"22222222-2222-4222-8222-222222222222","role":"authenticated","email":"b@example.com","phone":"+15550000002"}',
  $$SELECT count(*) FROM public.transcriptions WHERE title = 'A owned by user id'$$,
  0
);

SELECT public._assert_count(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  'SELECT count(*) FROM public.user_messages',
  1
);

SELECT public._assert_count(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  'SELECT count(*) FROM public.conversation_threads',
  1
);

SELECT public._assert_count(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  $$SELECT count(*) FROM public.conversation_messages WHERE content = 'B private chat'$$,
  0
);

SELECT public._assert_count(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  'SELECT count(*) FROM public.referrals',
  1
);

SELECT public._assert_count(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  $$SELECT count(*) FROM public.user_video_stats WHERE video_title = 'B video'$$,
  0
);

SELECT public._assert_count(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  'SELECT count(*) FROM public.tiktok_profile_stats',
  1
);

SELECT public._assert_count(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  'SELECT count(*) FROM public.credit_transactions',
  1
);

SELECT public._assert_count(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  'SELECT count(*) FROM public.credit_purchases',
  1
);

SELECT public._assert_count(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  'SELECT count(*) FROM public.profiles',
  1
);

SELECT public._assert_count(
  'authenticated',
  '{"sub":"22222222-2222-4222-8222-222222222222","role":"authenticated","email":"b@example.com","phone":"+15550000002"}',
  'SELECT count(*) FROM public.profiles',
  0
);

SELECT public._assert_count(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  'SELECT credits_remaining FROM public.sms_users',
  5
);

SELECT public._assert_denied(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  'SELECT otp_hash FROM public.sms_users'
);

SELECT public._assert_denied(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  $$UPDATE public.sms_users SET credits_remaining = 999 WHERE phone_number = '+15550000001'$$
);

SELECT public._assert_denied(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  $$UPDATE public.profiles SET credits = 999 WHERE id = '11111111-1111-4111-8111-111111111111'$$
);

SELECT public._assert_count(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  $$SELECT count(*) FROM public.video_comments WHERE text = 'comment on B'$$,
  0
);

SELECT public._assert_count(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  'SELECT count(*) FROM public.video_comments',
  1
);

SELECT public._assert_denied(
  'anon',
  '{"role":"anon"}',
  'SELECT count(*) FROM public.video_comments'
);

SELECT public._assert_denied(
  'anon',
  '{"role":"anon"}',
  $$SELECT public.atomic_credit_transaction('+15550000001', -1, 'transcription', 'stolen', '{}'::jsonb)$$
);

SELECT public._assert_denied(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  $$SELECT public.atomic_credit_transaction('+15550000002', -1, 'transcription', 'stolen', '{}'::jsonb)$$
);

SELECT public._assert_denied(
  'anon',
  '{"role":"anon"}',
  $$SELECT public.request_otp('+15550000001')$$
);

SELECT public._assert_denied(
  'anon',
  '{"role":"anon"}',
  $$SELECT public.fulfill_sms_credit_purchase('+15550000001', 'cs_stolen', 100, 'a@example.com', '{}'::jsonb)$$
);

-- service_role keeps the backend flows, including when BYPASSRLS is off.
ALTER ROLE service_role NOBYPASSRLS;

SELECT public._assert_count(
  'service_role',
  '{"role":"service_role"}',
  'SELECT count(*) FROM public.api_keys',
  1
);

SELECT public._assert_count(
  'service_role',
  '{"role":"service_role"}',
  'SELECT count(*) FROM public.user_messages',
  2
);

SELECT public._assert_count(
  'service_role',
  '{"role":"service_role"}',
  $$SELECT count(*) FROM (
     SELECT public.atomic_credit_transaction(
       '+15550000001', -1, 'transcription', 'sms deduction', '{}'::jsonb
     ) AS result
   ) AS deducted
   WHERE (result ->> 'success')::boolean$$,
  1
);

SELECT public._assert_count(
  'service_role',
  '{"role":"service_role"}',
  $$SELECT count(*) FROM (
     SELECT applied
     FROM public.fulfill_sms_credit_purchase(
       '+15550000002', 'cs_test_checkout', 10, 'b@example.com', '{"pack":10}'::jsonb
     )
   ) AS fulfilled
   WHERE applied$$,
  1
);

SELECT public._assert_count(
  'service_role',
  '{"role":"service_role"}',
  $$SELECT count(*) FROM (
     SELECT public.update_transcription(
       'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
       '{"status":"completed","title":"B updated by service"}'::jsonb
     ) AS result
   ) AS updated$$,
  1
);

DO $sms_inbound$
BEGIN
  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  EXECUTE 'SET LOCAL ROLE service_role';
  INSERT INTO public.user_messages (from_phone, to_phone, message_body, direction, message_sid)
  VALUES ('+15550000001', '+15559999999', 'inbound sms', 'inbound', 'SM-fixture-1');
END;
$sms_inbound$;

SELECT public._assert_count(
  'service_role',
  '{"role":"service_role"}',
  $$SELECT count(*) FROM public.user_messages WHERE message_sid = 'SM-fixture-1'$$,
  1
);

ALTER ROLE service_role BYPASSRLS;

-- The caller's own balance moved. The other user's balance did not, until fulfillment.
SELECT public._assert_count(
  'authenticated',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated","email":"a@example.com","phone":"+15550000001"}',
  'SELECT credits_remaining FROM public.sms_users',
  4
);

SELECT public._assert_count(
  'authenticated',
  '{"sub":"22222222-2222-4222-8222-222222222222","role":"authenticated","email":"b@example.com","phone":"+15550000002"}',
  'SELECT credits_remaining FROM public.sms_users',
  19
);

-- Browser insert/update/delete stays inside the caller's rows, and the trigger still runs.
DO $browser_write$
DECLARE
  seen_title text;
BEGIN
  PERFORM set_config(
    'request.jwt.claims',
    '{"sub":"22222222-2222-4222-8222-222222222222","role":"authenticated","email":"b@example.com","phone":"+15550000002"}',
    true
  );
  EXECUTE 'SET LOCAL ROLE authenticated';
  INSERT INTO public.profiles (id, email)
  VALUES ('22222222-2222-4222-8222-222222222222', 'b@example.com');

  INSERT INTO public.transcriptions (task_id, user_id, url, status, visibility, title)
  VALUES (
    'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
    '22222222-2222-4222-8222-222222222222',
    'https://example.com/b-new',
    'pending',
    'private',
    'B inserted'
  );

  UPDATE public.transcriptions
  SET title = 'B renamed'
  WHERE task_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

  UPDATE public.transcriptions
  SET title = 'stolen'
  WHERE task_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

  DELETE FROM public.transcriptions
  WHERE task_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

  INSERT INTO public.conversation_messages (thread_id, role, content)
  VALUES ('bcbcbcbc-bcbc-4bcb-8bcb-bcbcbcbcbcbc', 'user', 'B writes own thread');

  BEGIN
    INSERT INTO public.conversation_messages (thread_id, role, content)
    VALUES ('abababab-abab-4aba-8aba-abababababab', 'user', 'B writes A thread');
    RAISE EXCEPTION 'user B inserted into user A thread';
  EXCEPTION
    WHEN insufficient_privilege THEN
      NULL;
  END;
END;
$browser_write$;

DO $browser_write_check$
DECLARE
  b_title text;
  a_title text;
  a_still_there integer;
  b_profile integer;
BEGIN
  SELECT title INTO b_title
  FROM public.transcriptions
  WHERE task_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

  SELECT title INTO a_title
  FROM public.transcriptions
  WHERE task_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

  SELECT count(*) INTO a_still_there
  FROM public.transcriptions
  WHERE task_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

  SELECT count(*) INTO b_profile
  FROM public.profiles
  WHERE id = '22222222-2222-4222-8222-222222222222';

  IF b_title IS DISTINCT FROM 'B renamed' THEN
    RAISE EXCEPTION 'owner update failed, title is %', b_title;
  END IF;
  IF a_still_there <> 1 OR a_title IS DISTINCT FROM 'A owned by user id' THEN
    RAISE EXCEPTION 'user B modified user A transcription (present=%, title=%)', a_still_there, a_title;
  END IF;
  IF b_profile <> 1 THEN
    RAISE EXCEPTION 'user B profile insert failed';
  END IF;

  IF (
    SELECT count(*)
    FROM public.conversation_messages
    WHERE content = 'B writes own thread'
  ) <> 1 THEN
    RAISE EXCEPTION 'user B could not write their own thread';
  END IF;

  IF (
    SELECT count(*)
    FROM public.conversation_messages
    WHERE content = 'B writes A thread'
  ) <> 0 THEN
    RAISE EXCEPTION 'user B wrote into user A thread';
  END IF;
END;
$browser_write_check$;

-- search_path is pinned on the security-definer credit function.
DO $search_path$
DECLARE
  config text[];
BEGIN
  SELECT proconfig INTO config
  FROM pg_proc
  WHERE proname = 'atomic_credit_transaction';

  IF NOT ('search_path=public' = ANY (config)) THEN
    RAISE EXCEPTION 'atomic_credit_transaction search_path missing: %', config;
  END IF;
END;
$search_path$;

DROP FUNCTION public._assert_denied(text, text, text);
DROP FUNCTION public._assert_count(text, text, text, integer);
