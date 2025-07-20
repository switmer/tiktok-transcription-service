-- Function to get SMS user statistics
CREATE OR REPLACE FUNCTION get_sms_user_stats(p_phone_number text)
RETURNS TABLE (
  total_transcriptions bigint,
  monthly_transcriptions bigint,
  verified boolean,
  joined_date timestamp with time zone
) AS $$
BEGIN
  RETURN QUERY
  SELECT 
    COALESCE(COUNT(t.task_id), 0) as total_transcriptions,
    COALESCE(COUNT(t.task_id) FILTER (WHERE t.created_at >= date_trunc('month', NOW())), 0) as monthly_transcriptions,
    COALESCE(s.phone_verified, false) as verified,
    COALESCE(s.created_at, NOW()) as joined_date
  FROM transcriptions t
  RIGHT JOIN sms_users s ON s.phone_number = p_phone_number
  WHERE t.user_phone = p_phone_number OR t.user_phone IS NULL
  GROUP BY s.phone_verified, s.created_at;
  
  -- If no results, return defaults
  IF NOT FOUND THEN
    RETURN QUERY
    SELECT 
      0::bigint as total_transcriptions,
      0::bigint as monthly_transcriptions, 
      false as verified,
      NOW() as joined_date;
  END IF;
END;
$$ LANGUAGE plpgsql;

-- Function to normalize phone numbers
CREATE OR REPLACE FUNCTION normalize_phone_number(phone text)
RETURNS text AS $$
DECLARE
  digits text;
BEGIN
  -- Remove all non-digit characters
  digits := regexp_replace(phone, '[^0-9]', '', 'g');
  
  -- Add +1 if it's a 10-digit US number
  IF length(digits) = 10 THEN
    RETURN '+1' || digits;
  END IF;
  
  -- Add + if it doesn't start with + and is 11 digits starting with 1
  IF length(digits) = 11 AND left(digits, 1) = '1' THEN
    RETURN '+' || digits;
  END IF;
  
  -- Return original if we can't normalize
  RETURN phone;
END;
$$ LANGUAGE plpgsql;

-- Comments
COMMENT ON FUNCTION get_sms_user_stats(text) IS 'Get transcription statistics for SMS user by phone number';
COMMENT ON FUNCTION normalize_phone_number(text) IS 'Normalize phone number to +1XXXXXXXXXX format';