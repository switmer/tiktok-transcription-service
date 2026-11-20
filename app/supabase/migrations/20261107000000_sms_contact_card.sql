-- One-time ScribeTok contact-card (vCard) send tracking.
-- Only genuinely new sms_users rows are claimed. Legacy users stay NULL
-- and are never backfilled by application code.

ALTER TABLE public.sms_users
  ADD COLUMN IF NOT EXISTS contact_card_status text,
  ADD COLUMN IF NOT EXISTS contact_card_claimed_at timestamptz,
  ADD COLUMN IF NOT EXISTS contact_card_sent_at timestamptz,
  ADD COLUMN IF NOT EXISTS contact_card_error text,
  ADD COLUMN IF NOT EXISTS contact_card_message_sid text;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_sms_users_contact_card_status'
  ) THEN
    ALTER TABLE public.sms_users
      ADD CONSTRAINT chk_sms_users_contact_card_status
      CHECK (contact_card_status IS NULL OR contact_card_status IN ('claimed', 'sent', 'failed'));
  END IF;
END $$;

COMMENT ON COLUMN public.sms_users.contact_card_status IS
  'NULL = never eligible/claimed; claimed = in-flight; sent = MMS accepted by Twilio; failed = give up (no automatic retry)';

CREATE OR REPLACE FUNCTION public.claim_sms_contact_card(p_phone text)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  updated integer;
BEGIN
  IF p_phone IS NULL OR p_phone !~ '^\+[1-9][0-9]{9,14}$' THEN
    RETURN false;
  END IF;

  UPDATE public.sms_users
     SET contact_card_status = 'claimed',
         contact_card_claimed_at = timezone('utc', now()),
         contact_card_error = NULL
   WHERE phone_number = p_phone
     AND contact_card_status IS NULL
     AND contact_card_sent_at IS NULL;

  GET DIAGNOSTICS updated = ROW_COUNT;
  RETURN updated = 1;
END;
$$;

CREATE OR REPLACE FUNCTION public.complete_sms_contact_card(
    p_phone text,
    p_success boolean,
    p_error text DEFAULT NULL,
    p_message_sid text DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF p_success THEN
    UPDATE public.sms_users
       SET contact_card_status = 'sent',
           contact_card_sent_at = timezone('utc', now()),
           contact_card_error = NULL,
           contact_card_message_sid = p_message_sid
     WHERE phone_number = p_phone
       AND contact_card_status = 'claimed';
  ELSE
    UPDATE public.sms_users
       SET contact_card_status = 'failed',
           contact_card_error = left(coalesce(p_error, 'unknown'), 500),
           contact_card_message_sid = p_message_sid
     WHERE phone_number = p_phone
       AND contact_card_status = 'claimed';
  END IF;
END;
$$;

REVOKE ALL ON FUNCTION public.claim_sms_contact_card(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_sms_contact_card(text) TO service_role;

REVOKE ALL ON FUNCTION public.complete_sms_contact_card(text, boolean, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.complete_sms_contact_card(text, boolean, text, text) TO service_role;
