-- Create atomic_credit_transaction function for bulletproof credit operations
-- This function ensures atomic updates with complete audit trail and race condition prevention

CREATE OR REPLACE FUNCTION atomic_credit_transaction(
    user_phone_param text,
    credit_change integer,
    transaction_type text,
    description text,
    metadata jsonb DEFAULT '{}'
) RETURNS jsonb AS $$
DECLARE
    current_balance integer;
    new_balance integer;
    transaction_id uuid;
    user_exists boolean;
    result jsonb;
BEGIN
    -- Validate transaction type
    IF transaction_type NOT IN (
        'transcription', 'purchase', 'referral_bonus', 'admin_adjustment',
        'refund', 'refund_reversal', 'bulk_transcription', 'enterprise_purchase'
    ) THEN
        RAISE EXCEPTION 'Invalid transaction type: %', transaction_type;
    END IF;

    -- Lock the user row for update to prevent race conditions
    SELECT credits_remaining INTO current_balance
    FROM sms_users 
    WHERE phone_number = user_phone_param
    FOR UPDATE;

    -- Check if user exists
    IF NOT FOUND THEN
        RAISE EXCEPTION 'User not found: %', user_phone_param;
    END IF;

    -- Calculate new balance
    new_balance := current_balance + credit_change;

    -- Prevent negative balances for deductions
    IF new_balance < 0 THEN
        -- Log failed transaction
        INSERT INTO credit_transactions (
            user_phone, transaction_type, credit_change,
            balance_before, balance_after, description, metadata, success
        ) VALUES (
            user_phone_param, transaction_type, credit_change,
            current_balance, current_balance, description, metadata, false
        ) RETURNING id INTO transaction_id;

        -- Return failure result
        RETURN jsonb_build_object(
            'success', false,
            'transaction_id', transaction_id,
            'balance_before', current_balance,
            'new_balance', current_balance,
            'credit_change', credit_change,
            'error', 'Insufficient credits'
        );
    END IF;

    -- Update user balance atomically
    UPDATE sms_users 
    SET 
        credits_remaining = new_balance,
        last_active = now(),
        total_videos_transcribed = CASE 
            WHEN transaction_type = 'transcription' THEN total_videos_transcribed + 1
            ELSE total_videos_transcribed
        END,
        total_credits_purchased = CASE
            WHEN transaction_type IN ('purchase', 'enterprise_purchase') THEN total_credits_purchased + credit_change
            ELSE total_credits_purchased
        END
    WHERE phone_number = user_phone_param;

    -- Log successful transaction
    INSERT INTO credit_transactions (
        user_phone, transaction_type, credit_change,
        balance_before, balance_after, description, metadata, success
    ) VALUES (
        user_phone_param, transaction_type, credit_change,
        current_balance, new_balance, description, metadata, true
    ) RETURNING id INTO transaction_id;

    -- Return success result
    RETURN jsonb_build_object(
        'success', true,
        'transaction_id', transaction_id,
        'balance_before', current_balance,
        'new_balance', new_balance,
        'credit_change', credit_change,
        'transaction_type', transaction_type
    );

EXCEPTION
    WHEN OTHERS THEN
        -- Log error and re-raise
        RAISE EXCEPTION 'Credit transaction failed: %', SQLERRM;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant execute permission to authenticated users
GRANT EXECUTE ON FUNCTION atomic_credit_transaction(text, integer, text, text, jsonb) TO authenticated;
GRANT EXECUTE ON FUNCTION atomic_credit_transaction(text, integer, text, text, jsonb) TO service_role;

-- Add comment for documentation
COMMENT ON FUNCTION atomic_credit_transaction IS 'Atomically updates user credits with complete audit trail and race condition prevention';

-- Create convenience function for simple credit deduction
CREATE OR REPLACE FUNCTION atomic_deduct_credits(
    user_phone_param text,
    credits_to_deduct integer DEFAULT 1,
    description text DEFAULT 'Video transcription'
) RETURNS jsonb AS $$
BEGIN
    RETURN atomic_credit_transaction(
        user_phone_param, 
        -credits_to_deduct, 
        'transcription', 
        description
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant execute permission to convenience function
GRANT EXECUTE ON FUNCTION atomic_deduct_credits(text, integer, text) TO authenticated;
GRANT EXECUTE ON FUNCTION atomic_deduct_credits(text, integer, text) TO service_role;

COMMENT ON FUNCTION atomic_deduct_credits IS 'Convenience function for deducting credits during transcription';