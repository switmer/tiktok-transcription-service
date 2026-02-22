-- Fix: Remove phantom message logging from transcription completion trigger.
--
-- The trigger was calling safe_message_log to create an "outbound" record in
-- user_messages every time a transcription completed. This record had no
-- message_sid (never actually sent via Twilio) and used a hardcoded fake
-- phone number (+15551234567). The backend's send_completion_sms idempotency
-- check then found this phantom record and skipped sending the real SMS.
--
-- The backend already logs the real outbound message (with message_sid) after
-- sending via Twilio, so the trigger's logging was both redundant and harmful.
-- The trigger's sms_users stats update is kept intact.

CREATE OR REPLACE FUNCTION notify_transcription_complete_v2()
RETURNS TRIGGER AS $$
BEGIN
    -- Only fire for completed transcriptions with user_phone
    IF NEW.status = 'completed' AND NEW.user_phone IS NOT NULL
       AND (OLD.status IS NULL OR OLD.status != 'completed') THEN

        -- Update user stats atomically
        UPDATE sms_users
        SET total_videos_transcribed = total_videos_transcribed + 1,
            last_active = CURRENT_TIMESTAMP,
            most_popular_video_id = CASE
                WHEN NEW.like_count > COALESCE(most_popular_video_views, 0)
                THEN NEW.task_id::text
                ELSE most_popular_video_id
            END,
            most_popular_video_views = CASE
                WHEN NEW.like_count > COALESCE(most_popular_video_views, 0)
                THEN NEW.like_count
                ELSE most_popular_video_views
            END
        WHERE phone_number = NEW.user_phone;

    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Clean up phantom messages created by the old trigger.
-- These have no message_sid and were never actually sent.
DELETE FROM user_messages
WHERE message_sid IS NULL
  AND direction = 'outbound'
  AND command = 'transcription_complete';
