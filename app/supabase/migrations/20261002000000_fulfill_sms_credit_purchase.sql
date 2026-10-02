-- A Stripe session may be delivered more than once. Record and credit it in one transaction.
-- Older purchase triggers also add credits; remove them before using this function.
DROP TRIGGER IF EXISTS trigger_credit_purchase ON public.credit_purchases;
DROP TRIGGER IF EXISTS trigger_credit_purchase_v2 ON public.credit_purchases;

CREATE OR REPLACE FUNCTION public.fulfill_sms_credit_purchase(
    p_phone_number text,
    p_session_id text,
    p_credits integer,
    p_customer_email text DEFAULT NULL,
    p_products jsonb DEFAULT NULL
)
RETURNS TABLE(applied boolean, new_balance integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_existing public.credit_purchases%ROWTYPE;
BEGIN
    IF p_phone_number !~ '^\+[1-9][0-9]{9,14}$'
       OR p_session_id !~ '^cs_[A-Za-z0-9_]+$'
       OR p_credits <= 0 THEN
        RAISE EXCEPTION 'Invalid SMS purchase';
    END IF;

    -- Lock the existing SMS user; never create an account from checkout input.
    SELECT s.credits_remaining INTO new_balance
    FROM public.sms_users AS s
    WHERE s.phone_number = p_phone_number
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SMS user does not exist';
    END IF;

    INSERT INTO public.credit_purchases
        (phone_number, session_id, credits_purchased, customer_email, products)
    VALUES
        (p_phone_number, p_session_id, p_credits, p_customer_email, p_products)
    ON CONFLICT (session_id) DO NOTHING;

    IF NOT FOUND THEN
        SELECT * INTO v_existing
        FROM public.credit_purchases
        WHERE session_id = p_session_id;
        IF v_existing.phone_number IS DISTINCT FROM p_phone_number
           OR v_existing.credits_purchased IS DISTINCT FROM p_credits THEN
            RAISE EXCEPTION 'Stripe session is linked to a different purchase';
        END IF;
        applied := false;
        RETURN NEXT;
        RETURN;
    END IF;

    UPDATE public.sms_users AS s
    SET credits_remaining = COALESCE(s.credits_remaining, 0) + p_credits,
        total_credits_purchased = COALESCE(s.total_credits_purchased, 0) + p_credits
    WHERE s.phone_number = p_phone_number
    RETURNING s.credits_remaining INTO new_balance;
    applied := true;
    RETURN NEXT;
END;
$$;

REVOKE ALL ON FUNCTION public.fulfill_sms_credit_purchase(text, text, integer, text, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fulfill_sms_credit_purchase(text, text, integer, text, jsonb) TO service_role;
