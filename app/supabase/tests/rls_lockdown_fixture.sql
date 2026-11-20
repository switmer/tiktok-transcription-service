-- Minimal stand-in for the production public schema.
-- Used only by rls_lockdown_test.sh. Not a migration.

CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.users (
  id uuid PRIMARY KEY,
  email text
);

CREATE OR REPLACE FUNCTION auth.uid()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('request.jwt.claims', true)::jsonb ->> 'sub', '')::uuid;
$$;

CREATE OR REPLACE FUNCTION auth.jwt()
RETURNS jsonb
LANGUAGE sql
STABLE
AS $$
  SELECT COALESCE(current_setting('request.jwt.claims', true)::jsonb, '{}'::jsonb);
$$;

CREATE OR REPLACE FUNCTION auth.role()
RETURNS text
LANGUAGE sql
STABLE
AS $$
  SELECT COALESCE(
    NULLIF(current_setting('request.jwt.claims', true)::jsonb ->> 'role', ''),
    current_user
  );
$$;

GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA auth TO anon, authenticated, service_role;

DO $$
BEGIN
  CREATE TYPE public.visibility_type AS ENUM ('private', 'unlisted', 'public');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE public.sms_users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_number text NOT NULL UNIQUE,
  phone_verified boolean DEFAULT false,
  verification_code text,
  verification_expires timestamptz,
  session_token text,
  session_expires timestamptz,
  last_active timestamptz,
  created_at timestamptz DEFAULT now(),
  auth_user_id uuid REFERENCES auth.users (id),
  credits_remaining integer DEFAULT 5,
  free_credits_used integer DEFAULT 0,
  total_credits_purchased integer DEFAULT 0,
  referral_code text UNIQUE,
  referred_by text,
  referrals_count integer DEFAULT 0,
  total_referral_credits_earned integer DEFAULT 0,
  referral_streak integer DEFAULT 0,
  last_referral_date timestamptz,
  display_name text,
  tiktok_handle text,
  tiktok_profile_url text,
  tiktok_linked_at timestamptz,
  total_videos_transcribed integer DEFAULT 0,
  most_popular_video_id text,
  most_popular_video_views integer DEFAULT 0,
  updated_at timestamptz DEFAULT now(),
  email text UNIQUE,
  monthly_transcriptions integer DEFAULT 0,
  otp_hash text,
  otp_nonce text,
  otp_attempts integer DEFAULT 0,
  otp_locked_until timestamptz,
  otp_send_count integer DEFAULT 0,
  otp_send_window_start timestamptz
);

CREATE TABLE public.transcriptions (
  task_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES auth.users (id),
  url text NOT NULL,
  status text DEFAULT 'pending',
  created_at timestamptz DEFAULT now() NOT NULL,
  updated_at timestamptz DEFAULT now() NOT NULL,
  video_id text,
  title text,
  error text,
  thumbnail_url text,
  thumbnail_local_path text,
  transcript_file_path text,
  callback_url text,
  visibility public.visibility_type DEFAULT 'public',
  tags text[],
  category text,
  view_count integer DEFAULT 0,
  last_viewed_at timestamptz,
  transcript text,
  user_phone text,
  source text,
  metadata jsonb,
  description text,
  duration integer,
  upload_date text,
  "timestamp" bigint,
  channel text,
  channel_id text,
  uploader text,
  uploader_url text,
  like_count bigint DEFAULT 0,
  comment_count bigint DEFAULT 0,
  repost_count bigint DEFAULT 0,
  resolution text,
  width integer,
  height integer,
  aspect_ratio real,
  filesize bigint,
  format_id text,
  vcodec text,
  acodec text,
  audio_file_path text,
  info_file_path text,
  auto_tags text[],
  content_category text,
  language text,
  platform text,
  video_url text,
  quote text,
  tldr jsonb,
  supabase_thumbnail_url text,
  square_thumbnail_url text,
  raw_metadata jsonb
);

CREATE TABLE public.api_keys (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_description text,
  api_key text UNIQUE NOT NULL,
  created_at timestamptz DEFAULT now() NOT NULL,
  is_active boolean DEFAULT true NOT NULL
);

ALTER TABLE public.api_keys ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow service role access"
  ON public.api_keys
  FOR ALL
  USING (true)
  WITH CHECK (true);

CREATE TABLE public.user_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  from_phone text NOT NULL,
  message_body text NOT NULL,
  command text,
  created_at timestamptz DEFAULT now() NOT NULL,
  response_sent boolean DEFAULT false,
  direction text DEFAULT 'inbound',
  to_phone text,
  message_sid text UNIQUE,
  delivery_status text,
  error_code text,
  delivered_at timestamptz,
  failed_at timestamptz
);

CREATE TABLE public.referrals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  referrer_phone text NOT NULL,
  referee_phone text NOT NULL,
  credits_awarded integer DEFAULT 5,
  created_at timestamptz DEFAULT now(),
  referee_display_name text,
  referrer_total_earned integer DEFAULT 0,
  status text DEFAULT 'active'
);

CREATE TABLE public.user_video_stats (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_phone text NOT NULL,
  video_id text NOT NULL,
  video_url text NOT NULL,
  video_title text,
  video_author text,
  video_author_handle text,
  view_count integer,
  like_count integer,
  comment_count integer,
  share_count integer,
  transcribed_at timestamptz DEFAULT now(),
  is_users_video boolean DEFAULT false
);

CREATE TABLE public.tiktok_profile_stats (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tiktok_handle text NOT NULL,
  follower_count integer,
  following_count integer,
  total_likes integer,
  total_videos integer,
  verified boolean DEFAULT false,
  snapshot_date timestamptz DEFAULT now()
);

CREATE TABLE public.credit_purchases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_number text NOT NULL,
  session_id text NOT NULL UNIQUE,
  credits_purchased integer NOT NULL,
  purchase_timestamp timestamptz DEFAULT now(),
  customer_email text,
  products jsonb,
  created_at timestamptz DEFAULT now()
);

ALTER TABLE public.credit_purchases ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role can access all credit purchases"
  ON public.credit_purchases
  FOR ALL
  USING (auth.role() = 'service_role');
CREATE POLICY "Users can view their own purchases"
  ON public.credit_purchases
  FOR SELECT
  USING (
    auth.role() = 'authenticated'
    AND customer_email = (auth.jwt() ->> 'email')
  );

CREATE TABLE public.credit_transactions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_phone text NOT NULL,
  transaction_type text NOT NULL,
  credit_change integer NOT NULL,
  balance_before integer NOT NULL,
  balance_after integer NOT NULL,
  description text NOT NULL,
  metadata jsonb DEFAULT '{}'::jsonb,
  success boolean NOT NULL DEFAULT true,
  created_at timestamptz DEFAULT now() NOT NULL
);

ALTER TABLE public.credit_transactions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own credit transactions"
  ON public.credit_transactions
  FOR SELECT
  USING (user_phone = current_setting('app.current_user_phone', true));
CREATE POLICY "Service role can manage all credit transactions"
  ON public.credit_transactions
  FOR ALL
  USING (current_setting('role') = 'service_role');

CREATE TABLE public.profiles (
  id uuid PRIMARY KEY,
  email text NOT NULL UNIQUE,
  credits integer DEFAULT 0,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE TABLE public.schema_cache (
  key text PRIMARY KEY,
  payload jsonb NOT NULL,
  refreshed_at timestamptz DEFAULT now() NOT NULL
);

CREATE TABLE public.conversation_threads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_phone text NOT NULL,
  task_id uuid NOT NULL,
  summary text,
  message_count integer NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'active',
  last_active timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  closed_at timestamptz
);

CREATE TABLE public.conversation_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  thread_id uuid NOT NULL REFERENCES public.conversation_threads (id) ON DELETE CASCADE,
  role text NOT NULL,
  content text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.video_comments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid NOT NULL,
  comment_id text NOT NULL,
  video_id text NOT NULL,
  text text NOT NULL,
  author_name text NOT NULL,
  author_username text NOT NULL
);

ALTER TABLE public.video_comments ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow public read" ON public.video_comments FOR SELECT USING (true);
CREATE POLICY "Allow service role"
  ON public.video_comments
  FOR ALL
  TO service_role
  USING (true);

CREATE TABLE public.comments_fetch_progress (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid UNIQUE,
  video_id text NOT NULL,
  status text NOT NULL
);

ALTER TABLE public.comments_fetch_progress ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow public read" ON public.comments_fetch_progress FOR SELECT USING (true);
CREATE POLICY "Allow service role"
  ON public.comments_fetch_progress
  FOR ALL
  TO service_role
  USING (true);

CREATE TABLE public.cost_tracking (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at timestamptz DEFAULT now() NOT NULL,
  cost_type text NOT NULL,
  amount_cents integer DEFAULT 0 NOT NULL,
  user_phone text,
  task_id text,
  metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
  success boolean DEFAULT true NOT NULL,
  error_message text
);

ALTER TABLE public.cost_tracking ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role can manage cost tracking"
  ON public.cost_tracking
  FOR ALL
  USING (current_setting('role') = 'service_role');

CREATE TABLE public.twilio_error_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  twilio_sid text NOT NULL,
  account_sid text NOT NULL,
  payload_data jsonb
);

ALTER TABLE public.twilio_error_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow service role full access to twilio_error_logs"
  ON public.twilio_error_logs
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE TABLE public.pending_referrals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  referral_code text NOT NULL,
  created_at timestamptz DEFAULT now(),
  expires_at timestamptz NOT NULL,
  used_by text,
  ip_address text,
  user_agent text
);

ALTER TABLE public.pending_referrals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role can access all pending referrals"
  ON public.pending_referrals
  FOR ALL
  USING (auth.role() = 'service_role');

CREATE OR REPLACE FUNCTION public.touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TRIGGER transcriptions_touch
  BEFORE UPDATE ON public.transcriptions
  FOR EACH ROW
  EXECUTE FUNCTION public.touch_updated_at();

CREATE OR REPLACE FUNCTION public.atomic_credit_transaction(
  user_phone_param text,
  credit_change integer,
  transaction_type text,
  description text,
  metadata jsonb DEFAULT '{}'::jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  current_balance integer;
  new_balance integer;
  transaction_id uuid;
BEGIN
  SELECT credits_remaining
    INTO current_balance
  FROM public.sms_users
  WHERE phone_number = user_phone_param
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'User not found: %', user_phone_param;
  END IF;

  new_balance := current_balance + credit_change;
  IF new_balance < 0 THEN
    RETURN jsonb_build_object('success', false, 'new_balance', current_balance);
  END IF;

  UPDATE public.sms_users
  SET credits_remaining = new_balance
  WHERE phone_number = user_phone_param;

  INSERT INTO public.credit_transactions (
    user_phone, transaction_type, credit_change, balance_before, balance_after, description, metadata, success
  )
  VALUES (
    user_phone_param, transaction_type, credit_change, current_balance, new_balance, description, metadata, true
  )
  RETURNING id INTO transaction_id;

  RETURN jsonb_build_object('success', true, 'transaction_id', transaction_id, 'new_balance', new_balance);
END;
$$;

CREATE OR REPLACE FUNCTION public.fulfill_sms_credit_purchase(
  p_phone_number text,
  p_session_id text,
  p_credits integer,
  p_customer_email text DEFAULT NULL,
  p_products jsonb DEFAULT NULL
)
RETURNS TABLE (applied boolean, new_balance integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE public.sms_users AS s
  SET credits_remaining = COALESCE(s.credits_remaining, 0) + p_credits,
      total_credits_purchased = COALESCE(s.total_credits_purchased, 0) + p_credits
  WHERE s.phone_number = p_phone_number
  RETURNING s.credits_remaining INTO new_balance;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'SMS user does not exist';
  END IF;

  INSERT INTO public.credit_purchases (phone_number, session_id, credits_purchased, customer_email, products)
  VALUES (p_phone_number, p_session_id, p_credits, p_customer_email, p_products);

  applied := true;
  RETURN NEXT;
END;
$$;

REVOKE ALL ON FUNCTION public.fulfill_sms_credit_purchase(text, text, integer, text, jsonb)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fulfill_sms_credit_purchase(text, text, integer, text, jsonb)
  TO service_role;

CREATE OR REPLACE FUNCTION public.request_otp(p_phone_e164 text)
RETURNS text
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN '123456';
END;
$$;

CREATE OR REPLACE FUNCTION public.update_transcription(p_task_id uuid, p_update_data jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE public.transcriptions
  SET title = COALESCE(p_update_data ->> 'title', title),
      status = COALESCE(p_update_data ->> 'status', status)
  WHERE task_id = p_task_id;
  RETURN jsonb_build_object('task_id', p_task_id);
END;
$$;

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
      WHEN t.status = 'completed' THEN 'completed'
      WHEN t.status = 'failed' THEN 'failed'
      WHEN t.status = 'processing' THEN 'processing'
      ELSE 'pending'
    END AS unified_status
   FROM public.transcriptions t
  WHERE t.user_phone IS NOT NULL
    AND t.created_at >= (CURRENT_DATE - '7 days'::interval)
  ORDER BY t.created_at DESC;

GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.fulfill_sms_credit_purchase(text, text, integer, text, jsonb)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fulfill_sms_credit_purchase(text, text, integer, text, jsonb)
  TO service_role;

INSERT INTO auth.users (id, email) VALUES
  ('11111111-1111-4111-8111-111111111111', 'a@example.com'),
  ('22222222-2222-4222-8222-222222222222', 'b@example.com');

INSERT INTO public.sms_users (
  id, phone_number, auth_user_id, email, credits_remaining, referral_code,
  display_name, tiktok_handle, otp_hash, verification_code, session_token
) VALUES
  (
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1',
    '+15550000001',
    '11111111-1111-4111-8111-111111111111',
    'a@example.com',
    5,
    'REF-A',
    'User A',
    'user_a',
    'otp-hash-a',
    '111111',
    'session-a'
  ),
  (
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2',
    '+15550000002',
    '22222222-2222-4222-8222-222222222222',
    'b@example.com',
    9,
    'REF-B',
    'User B',
    'user_b',
    'otp-hash-b',
    '222222',
    'session-b'
  );

INSERT INTO public.profiles (id, email, credits) VALUES
  ('11111111-1111-4111-8111-111111111111', 'a@example.com', 0);

INSERT INTO public.api_keys (id, api_key, user_description, is_active) VALUES
  ('99999999-9999-4999-8999-999999999999', 'test-secret-key', 'fixture', true);

INSERT INTO public.schema_cache (key, payload) VALUES
  ('tables', '{"secret": true}'::jsonb);

INSERT INTO public.transcriptions (
  task_id, user_id, user_phone, url, status, visibility, title, transcript, callback_url, transcript_file_path
) VALUES
  (
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    '11111111-1111-4111-8111-111111111111',
    '+15550000001',
    'https://example.com/a-owned',
    'completed',
    'private',
    'A owned by user id',
    'secret transcript a',
    'https://callback.example/a',
    '/tmp/a.txt'
  ),
  (
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaab',
    NULL,
    '+15550000001',
    'https://example.com/a-phone',
    'completed',
    'private',
    'A owned by phone',
    'secret transcript a phone',
    NULL,
    NULL
  ),
  (
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    '22222222-2222-4222-8222-222222222222',
    '+15550000002',
    'https://example.com/b-owned',
    'completed',
    'private',
    'B owned',
    'secret transcript b',
    'https://callback.example/b',
    '/tmp/b.txt'
  ),
  (
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    NULL,
    '+15550000002',
    'https://example.com/public',
    'completed',
    'public',
    'Public completed',
    'public transcript',
    'https://callback.example/public',
    '/tmp/public.txt'
  ),
  (
    'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    NULL,
    '+15550000002',
    'https://example.com/failed-public',
    'failed',
    'public',
    'Public failed',
    NULL,
    NULL,
    NULL
  );

INSERT INTO public.user_messages (from_phone, to_phone, message_body, direction) VALUES
  ('+15550000001', '+15559999999', 'hello from A', 'inbound'),
  ('+15559999999', '+15550000002', 'hello to B', 'outbound');

INSERT INTO public.referrals (referrer_phone, referee_phone) VALUES
  ('+15550000001', '+15550000002');

INSERT INTO public.user_video_stats (user_phone, video_id, video_url, video_title) VALUES
  ('+15550000001', 'vid-a', 'https://example.com/vid-a', 'A video'),
  ('+15550000002', 'vid-b', 'https://example.com/vid-b', 'B video');

INSERT INTO public.tiktok_profile_stats (tiktok_handle, follower_count) VALUES
  ('user_a', 10),
  ('user_b', 20);

INSERT INTO public.credit_purchases (phone_number, session_id, credits_purchased, customer_email) VALUES
  ('+15550000001', 'cs_fixture_a', 5, 'a@example.com'),
  ('+15550000002', 'cs_fixture_b', 10, 'b@example.com');

INSERT INTO public.credit_transactions (
  user_phone, transaction_type, credit_change, balance_before, balance_after, description
) VALUES
  ('+15550000001', 'purchase', 5, 0, 5, 'A purchase'),
  ('+15550000002', 'purchase', 10, 0, 10, 'B purchase');

INSERT INTO public.conversation_threads (id, user_phone, task_id, summary) VALUES
  ('abababab-abab-4aba-8aba-abababababab', '+15550000001', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'A thread'),
  ('bcbcbcbc-bcbc-4bcb-8bcb-bcbcbcbcbcbc', '+15550000002', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'B thread');

INSERT INTO public.conversation_messages (thread_id, role, content) VALUES
  ('abababab-abab-4aba-8aba-abababababab', 'user', 'A private chat'),
  ('bcbcbcbc-bcbc-4bcb-8bcb-bcbcbcbcbcbc', 'user', 'B private chat');

INSERT INTO public.video_comments (task_id, comment_id, video_id, text, author_name, author_username) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'c-a', 'vid-a', 'comment on A', 'Ann', 'ann'),
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'c-b', 'vid-b', 'comment on B', 'Bob', 'bob');

INSERT INTO public.comments_fetch_progress (task_id, video_id, status) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'vid-a', 'completed'),
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'vid-b', 'completed');

INSERT INTO public.cost_tracking (cost_type, amount_cents, user_phone) VALUES
  ('openai_whisper', 12, '+15550000001');

INSERT INTO public.twilio_error_logs (twilio_sid, account_sid, payload_data) VALUES
  ('SM123', 'AC123', '{"phone":"+15550000001"}'::jsonb);

INSERT INTO public.pending_referrals (referral_code, expires_at, ip_address) VALUES
  ('REF-A', now() + interval '1 day', '203.0.113.5');
