-- Minimal, defensible OTP hardening for SMS login
-- - Crypto RNG OTP generation (pgcrypto)
-- - Hash OTP at rest (HMAC-SHA256 with server secret + nonce)
-- - Attempt counter + lockout window
-- - Resend limiter
--
-- IMPORTANT: You must set the DB secret once (run in Supabase SQL editor):
--   ALTER DATABASE postgres SET app.otp_secret = '<strong-random-secret>';
-- Then restart connections (or wait for new connections).

create extension if not exists pgcrypto;

alter table public.sms_users
  add column if not exists otp_hash text,
  add column if not exists otp_nonce text,
  add column if not exists otp_attempts int default 0,
  add column if not exists otp_locked_until timestamptz,
  add column if not exists otp_send_count int default 0,
  add column if not exists otp_send_window_start timestamptz;

comment on column public.sms_users.otp_hash is 'HMAC-SHA256 of (phone:code:nonce) using app.otp_secret';
comment on column public.sms_users.otp_nonce is 'Random nonce used when hashing OTP';
comment on column public.sms_users.otp_attempts is 'Failed verify attempts for current OTP window';
comment on column public.sms_users.otp_locked_until is 'If set and in the future, OTP verify is locked out';
comment on column public.sms_users.otp_send_count is 'OTP sends in current resend window';
comment on column public.sms_users.otp_send_window_start is 'Start of OTP resend window';

create or replace function public.request_otp(p_phone_e164 text)
returns table(success boolean, code text, expires_at timestamptz, error text)
language plpgsql
as $$
declare
  v_secret text;
  v_now timestamptz := now();
  v_window_start timestamptz;
  v_send_count int;
  v_code_int int;
  v_code text;
  v_nonce text;
  v_hash text;
  v_expires timestamptz := v_now + interval '10 minutes';
begin
  if coalesce(current_setting('request.jwt.claim.role', true), '') <> 'service_role' then
    raise exception 'request_otp is service-only'
      using errcode = '42501';
  end if;
  if p_phone_e164 is null or p_phone_e164 !~ '^\+1[0-9]{10}$' then
    return query select false, null::text, null::timestamptz, 'Invalid phone number'::text;
    return;
  end if;

  v_secret := current_setting('app.otp_secret', true);
  if v_secret is null or length(v_secret) < 16 then
    raise exception 'OTP not configured'
      using errcode = 'P0001', detail = 'Missing app.otp_secret';
  end if;

  -- Lock row to serialize OTP issuance and counters
  select otp_send_window_start, otp_send_count
    into v_window_start, v_send_count
  from public.sms_users
  where phone_number = p_phone_e164
  for update;

  if not found then
    return query select false, null::text, null::timestamptz, 'User not found'::text;
    return;
  end if;

  if v_window_start is null or v_window_start < (v_now - interval '10 minutes') then
    v_window_start := v_now;
    v_send_count := 0;
  end if;

  if coalesce(v_send_count, 0) >= 3 then
    return query select false, null::text, null::timestamptz, 'Too many OTP requests. Try again later.'::text;
    return;
  end if;

  -- Crypto RNG 6-digit code using pgcrypto bytes
  v_code_int := ((get_byte(gen_random_bytes(2), 0) * 256 + get_byte(gen_random_bytes(2), 1)) % 900000) + 100000;
  v_code := lpad(v_code_int::text, 6, '0');
  v_nonce := encode(gen_random_bytes(16), 'hex');
  v_hash := encode(hmac(p_phone_e164 || ':' || v_code || ':' || v_nonce, v_secret, 'sha256'), 'hex');

  update public.sms_users
  set
    otp_hash = v_hash,
    otp_nonce = v_nonce,
    otp_attempts = 0,
    otp_locked_until = null,
    verification_expires = v_expires,
    verification_code = null, -- legacy plaintext column
    otp_send_window_start = v_window_start,
    otp_send_count = coalesce(v_send_count, 0) + 1
  where phone_number = p_phone_e164;

  return query select true, v_code, v_expires, null::text;
end;
$$;

create or replace function public.verify_otp(p_phone_e164 text, p_code text)
returns jsonb
language plpgsql
as $$
declare
  v_secret text;
  v_now timestamptz := now();
  v_hash text;
  v_nonce text;
  v_attempts int;
  v_locked_until timestamptz;
  v_expires timestamptz;
  v_expected text;
  v_session_token text;
  v_session_expires timestamptz := v_now + interval '30 days';
begin
  if coalesce(current_setting('request.jwt.claim.role', true), '') <> 'service_role' then
    raise exception 'verify_otp is service-only'
      using errcode = '42501';
  end if;
  if p_phone_e164 is null or p_phone_e164 !~ '^\+1[0-9]{10}$' then
    return jsonb_build_object('success', false, 'error', 'Invalid phone number');
  end if;
  if p_code is null or length(p_code) <> 6 or p_code !~ '^[0-9]{6}$' then
    return jsonb_build_object('success', false, 'error', 'Invalid code format');
  end if;

  v_secret := current_setting('app.otp_secret', true);
  if v_secret is null or length(v_secret) < 16 then
    raise exception 'OTP not configured'
      using errcode = 'P0001', detail = 'Missing app.otp_secret';
  end if;

  select otp_hash, otp_nonce, otp_attempts, otp_locked_until, verification_expires
    into v_hash, v_nonce, v_attempts, v_locked_until, v_expires
  from public.sms_users
  where phone_number = p_phone_e164
  for update;

  if not found then
    return jsonb_build_object('success', false, 'error', 'User not found');
  end if;

  if v_locked_until is not null and v_locked_until > v_now then
    return jsonb_build_object('success', false, 'error', 'Locked out', 'locked_until', v_locked_until);
  end if;

  if v_expires is null or v_expires <= v_now or v_hash is null or v_nonce is null then
    return jsonb_build_object('success', false, 'error', 'Code expired. Request a new one with /login');
  end if;

  v_expected := encode(hmac(p_phone_e164 || ':' || p_code || ':' || v_nonce, v_secret, 'sha256'), 'hex');

  if v_expected <> v_hash then
    v_attempts := coalesce(v_attempts, 0) + 1;

    if v_attempts >= 6 then
      update public.sms_users
      set
        otp_attempts = 0,
        otp_locked_until = v_now + interval '15 minutes'
      where phone_number = p_phone_e164;

      return jsonb_build_object('success', false, 'error', 'Too many attempts. Try again later.');
    end if;

    update public.sms_users
    set otp_attempts = v_attempts
    where phone_number = p_phone_e164;

    return jsonb_build_object('success', false, 'error', 'Invalid code', 'attempts_remaining', 6 - v_attempts);
  end if;

  -- Success: issue session token and clear OTP state
  v_session_token := encode(gen_random_bytes(16), 'hex');

  update public.sms_users
  set
    phone_verified = true,
    session_token = v_session_token,
    session_expires = v_session_expires,
    otp_hash = null,
    otp_nonce = null,
    otp_attempts = 0,
    otp_locked_until = null,
    verification_expires = null,
    verification_code = null
  where phone_number = p_phone_e164;

  return jsonb_build_object(
    'success', true,
    'session_token', v_session_token,
    'session_expires', v_session_expires
  );
end;
$$;

revoke execute on function public.request_otp(text) from anon;
revoke execute on function public.request_otp(text) from authenticated;
grant execute on function public.request_otp(text) to service_role;

revoke execute on function public.verify_otp(text, text) from anon;
revoke execute on function public.verify_otp(text, text) from authenticated;
grant execute on function public.verify_otp(text, text) to service_role;








