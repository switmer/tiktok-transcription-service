-- Add account linking functionality for SMS users
-- Allows SMS users to "claim" their transcriptions when they register

-- Function to link SMS user transcriptions to a new auth account
CREATE OR REPLACE FUNCTION link_sms_user_to_auth(
    p_phone_number text,
    p_auth_user_id uuid
) RETURNS TABLE(linked_transcriptions integer) AS $$
DECLARE
    transcription_count integer;
BEGIN
    -- Update all transcriptions for this phone number
    UPDATE transcriptions 
    SET user_id = p_auth_user_id
    WHERE user_phone = p_phone_number 
    AND user_id IS NULL;
    
    GET DIAGNOSTICS transcription_count = ROW_COUNT;
    
    -- Also update the sms_users table to link to auth
    UPDATE sms_users 
    SET auth_user_id = p_auth_user_id
    WHERE phone_number = p_phone_number;
    
    RETURN QUERY SELECT transcription_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get SMS user stats for account linking (different name to avoid conflict)
CREATE OR REPLACE FUNCTION get_sms_linking_stats(p_phone_number text)
RETURNS TABLE(
    total_transcriptions integer,
    completed_transcriptions integer,
    first_transcription_date timestamptz,
    latest_transcription_date timestamptz
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        COUNT(*)::integer as total_transcriptions,
        COUNT(*) FILTER (WHERE status = 'completed')::integer as completed_transcriptions,
        MIN(created_at) as first_transcription_date,
        MAX(created_at) as latest_transcription_date
    FROM transcriptions
    WHERE user_phone = p_phone_number;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

SELECT 'Account linking functions created successfully' as result;