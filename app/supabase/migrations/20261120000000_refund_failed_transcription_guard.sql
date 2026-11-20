-- NOT APPLIED. Migration file only.
-- Do not run this against production until Steve approves.
--
-- deploy.yml would apply it via `supabase db push`, but that workflow does
-- not run today (it listens for "🧪 Continuous Integration & Testing" and
-- ci.yml is named "Continuous Integration"). Merging this pull request does
-- not apply the migration and does not deploy sms-inbound.
--
-- What it adds, once someone runs it on purpose:
--   * at most one successful refund per task_id
--   * refund_failed_transcription(task_id) returns without changing the
--     balance when that task was never charged or was already refunded
--
-- Until then, app/core/credit_refund.py does the same checks and calls the
-- existing atomic_credit_transaction RPC.

CREATE UNIQUE INDEX IF NOT EXISTS credit_transactions_one_successful_refund_per_task
    ON credit_transactions ((metadata->>'task_id'))
    WHERE transaction_type = 'refund'
      AND success = true
      AND COALESCE(metadata->>'task_id', '') <> '';

CREATE OR REPLACE FUNCTION refund_failed_transcription(p_task_id text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_task uuid;
    v_phone text;
    v_charge_id uuid;
    v_existing uuid;
    v_result jsonb;
BEGIN
    IF p_task_id IS NULL OR btrim(p_task_id) = '' THEN
        RETURN jsonb_build_object(
            'success', false,
            'refunded', false,
            'reason', 'missing_task_id'
        );
    END IF;

    BEGIN
        v_task := p_task_id::uuid;
    EXCEPTION
        WHEN invalid_text_representation THEN
            RETURN jsonb_build_object(
                'success', false,
                'refunded', false,
                'reason', 'bad_task_id'
            );
    END;

    -- One refund attempt per task at a time. The unique index is the backstop
    -- if a refund is inserted outside this function.
    PERFORM pg_advisory_xact_lock(hashtext('scribetok-refund'), hashtext(p_task_id));

    SELECT id INTO v_existing
    FROM credit_transactions
    WHERE transaction_type = 'refund'
      AND success = true
      AND metadata->>'task_id' = p_task_id
    LIMIT 1;

    IF v_existing IS NOT NULL THEN
        RETURN jsonb_build_object(
            'success', true,
            'refunded', false,
            'reason', 'already_refunded',
            'transaction_id', v_existing
        );
    END IF;

    SELECT id, user_phone INTO v_charge_id, v_phone
    FROM credit_transactions
    WHERE transaction_type = 'transcription'
      AND success = true
      AND credit_change < 0
      AND metadata->>'task_id' = p_task_id
    ORDER BY created_at ASC
    LIMIT 1;

    IF v_charge_id IS NULL THEN
        RETURN jsonb_build_object(
            'success', true,
            'refunded', false,
            'reason', 'never_charged'
        );
    END IF;

    IF v_phone IS NULL OR btrim(v_phone) = '' THEN
        SELECT user_phone INTO v_phone
        FROM transcriptions
        WHERE task_id = v_task;
    END IF;

    IF v_phone IS NULL OR btrim(v_phone) = '' THEN
        RETURN jsonb_build_object(
            'success', false,
            'refunded', false,
            'reason', 'no_phone'
        );
    END IF;

    v_result := atomic_credit_transaction(
        v_phone,
        1,
        'refund',
        'Refund for failed transcription',
        jsonb_build_object('task_id', p_task_id, 'charge_id', v_charge_id)
    );

    RETURN v_result || jsonb_build_object(
        'refunded', COALESCE((v_result->>'success')::boolean, false),
        'reason', CASE
            WHEN COALESCE((v_result->>'success')::boolean, false) THEN 'refunded'
            ELSE 'rpc_rejected'
        END
    );
EXCEPTION
    WHEN unique_violation THEN
        RETURN jsonb_build_object(
            'success', true,
            'refunded', false,
            'reason', 'already_refunded'
        );
    WHEN OTHERS THEN
        IF SQLERRM ILIKE '%duplicate key%'
           OR SQLERRM ILIKE '%credit_transactions_one_successful_refund%' THEN
            RETURN jsonb_build_object(
                'success', true,
                'refunded', false,
                'reason', 'already_refunded'
            );
        END IF;
        RETURN jsonb_build_object(
            'success', false,
            'refunded', false,
            'reason', 'error',
            'error', SQLERRM
        );
END;
$$;

GRANT EXECUTE ON FUNCTION refund_failed_transcription(text) TO service_role;

COMMENT ON FUNCTION refund_failed_transcription(text) IS
    'Refund one SMS credit for a failed transcription. Idempotent per task_id. No-op when that task was never charged. NOT applied to production by the pull request that added this file.';
