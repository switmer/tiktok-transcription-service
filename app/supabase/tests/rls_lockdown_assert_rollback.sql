-- After the rollback file, anon can read the tables that were open before,
-- and fulfill_sms_credit_purchase stays service_role-only.

DO $rollback_checks$
DECLARE
  message_count integer;
  key_count integer;
  transcription_count integer;
  job_count integer;
  otp text;
BEGIN
  EXECUTE 'SET LOCAL ROLE anon';

  SELECT count(*) INTO message_count FROM public.user_messages;
  IF message_count < 3 THEN
    RAISE EXCEPTION 'rollback: anon saw % user_messages, expected the full table', message_count;
  END IF;

  SELECT count(*) INTO key_count FROM public.api_keys;
  IF key_count <> 1 THEN
    RAISE EXCEPTION 'rollback: anon saw % api_keys', key_count;
  END IF;

  SELECT count(*) INTO transcription_count FROM public.transcriptions;
  IF transcription_count < 5 THEN
    RAISE EXCEPTION 'rollback: anon saw % transcriptions', transcription_count;
  END IF;

  SELECT count(*) INTO job_count FROM public.sms_job_status;
  IF job_count < 1 THEN
    RAISE EXCEPTION 'rollback: anon saw no sms_job_status rows';
  END IF;

  SELECT public.request_otp('+15550000001') INTO otp;
  IF otp IS DISTINCT FROM '123456' THEN
    RAISE EXCEPTION 'rollback: request_otp returned %', otp;
  END IF;
END;
$rollback_checks$;

DO $fulfill_still_locked$
BEGIN
  IF has_function_privilege(
    'anon',
    'public.fulfill_sms_credit_purchase(text,text,integer,text,jsonb)',
    'EXECUTE'
  ) THEN
    RAISE EXCEPTION 'rollback granted anon EXECUTE on fulfill_sms_credit_purchase';
  END IF;

  IF NOT has_function_privilege(
    'anon',
    'public.atomic_credit_transaction(text,integer,text,text,jsonb)',
    'EXECUTE'
  ) THEN
    RAISE EXCEPTION 'rollback did not restore anon EXECUTE on atomic_credit_transaction';
  END IF;

  IF NOT has_table_privilege('anon', 'public.user_messages', 'TRUNCATE') THEN
    RAISE EXCEPTION 'rollback did not restore anon TRUNCATE on user_messages';
  END IF;
END;
$fulfill_still_locked$;
