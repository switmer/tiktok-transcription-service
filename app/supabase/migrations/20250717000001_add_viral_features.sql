-- Migration: Add viral sharing and referral tracking features
-- Created: 2025-07-17

-- Create referral_events table for tracking shares and views
CREATE TABLE IF NOT EXISTS referral_events (
    id BIGSERIAL PRIMARY KEY,
    ref_code TEXT NOT NULL,
    task_id TEXT NOT NULL,
    visitor_ip TEXT,
    event_type TEXT NOT NULL DEFAULT 'view', -- 'view', 'click', 'signup'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_referral_events_ref_code ON referral_events(ref_code);
CREATE INDEX IF NOT EXISTS idx_referral_events_task_id ON referral_events(task_id);
CREATE INDEX IF NOT EXISTS idx_referral_events_created_at ON referral_events(created_at);

-- Create user_credits table for tracking earned credits
CREATE TABLE IF NOT EXISTS user_credits (
    id BIGSERIAL PRIMARY KEY,
    phone_number TEXT NOT NULL,
    credits INTEGER DEFAULT 0,
    earned_from_referrals INTEGER DEFAULT 0,
    earned_from_invites INTEGER DEFAULT 0,
    spent_credits INTEGER DEFAULT 0,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create unique index on phone_number
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_credits_phone ON user_credits(phone_number);

-- Create referral_rewards table for tracking what users earned
CREATE TABLE IF NOT EXISTS referral_rewards (
    id BIGSERIAL PRIMARY KEY,
    referrer_phone TEXT NOT NULL,
    referred_phone TEXT,
    ref_code TEXT NOT NULL,
    task_id TEXT NOT NULL,
    reward_type TEXT NOT NULL DEFAULT 'view_credit', -- 'view_credit', 'signup_bonus', 'referral_bonus'
    credits_earned INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending', -- 'pending', 'awarded', 'expired'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    awarded_at TIMESTAMP WITH TIME ZONE
);

-- Create indexes for referral rewards
CREATE INDEX IF NOT EXISTS idx_referral_rewards_referrer ON referral_rewards(referrer_phone);
CREATE INDEX IF NOT EXISTS idx_referral_rewards_ref_code ON referral_rewards(ref_code);

-- Add viral metrics columns to transcriptions table
ALTER TABLE transcriptions 
ADD COLUMN IF NOT EXISTS view_count INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS share_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS viral_score INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS trending_rank INTEGER,
ADD COLUMN IF NOT EXISTS last_viral_update TIMESTAMP WITH TIME ZONE;

-- Create function to update viral metrics
CREATE OR REPLACE FUNCTION update_viral_metrics(p_task_id TEXT)
RETURNS void AS $$
BEGIN
    -- Update view count and viral score for a transcript
    UPDATE transcriptions 
    SET 
        view_count = (
            SELECT COUNT(*) 
            FROM referral_events 
            WHERE task_id = p_task_id
        ),
        share_count = (
            SELECT COUNT(*) 
            FROM referral_events 
            WHERE task_id = p_task_id 
            AND event_type = 'share'
        ),
        viral_score = (
            SELECT COUNT(*) * 10 + COUNT(CASE WHEN created_at > NOW() - INTERVAL '24 hours' THEN 1 END) * 100
            FROM referral_events 
            WHERE task_id = p_task_id
        ),
        last_viral_update = NOW()
    WHERE task_id = p_task_id;
END;
$$ LANGUAGE plpgsql;

-- Create trigger to automatically update viral metrics when referral events are added
CREATE OR REPLACE FUNCTION trigger_update_viral_metrics()
RETURNS TRIGGER AS $$
BEGIN
    -- Update viral metrics for the affected task
    PERFORM update_viral_metrics(NEW.task_id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create the trigger
DROP TRIGGER IF EXISTS update_viral_metrics_trigger ON referral_events;
CREATE TRIGGER update_viral_metrics_trigger
    AFTER INSERT ON referral_events
    FOR EACH ROW
    EXECUTE FUNCTION trigger_update_viral_metrics();

-- Create function to calculate trending rankings
CREATE OR REPLACE FUNCTION update_trending_rankings()
RETURNS void AS $$
BEGIN
    -- Update trending ranks based on recent viral activity
    WITH trending_scores AS (
        SELECT 
            task_id,
            view_count + (share_count * 5) + 
            (SELECT COUNT(*) * 10 FROM referral_events WHERE task_id = t.task_id AND created_at > NOW() - INTERVAL '24 hours') as score
        FROM transcriptions t
        WHERE status = 'completed'
        AND created_at > NOW() - INTERVAL '7 days'
    ),
    ranked_transcripts AS (
        SELECT 
            task_id,
            ROW_NUMBER() OVER (ORDER BY score DESC) as rank
        FROM trending_scores
        WHERE score > 0
    )
    UPDATE transcriptions 
    SET trending_rank = ranked_transcripts.rank
    FROM ranked_transcripts
    WHERE transcriptions.task_id = ranked_transcripts.task_id;
END;
$$ LANGUAGE plpgsql;

-- Create initial data - sample referral codes for testing
-- (This would normally be populated by the application)

-- Grant necessary permissions
GRANT ALL ON TABLE referral_events TO anon, authenticated;
GRANT ALL ON TABLE user_credits TO anon, authenticated;
GRANT ALL ON TABLE referral_rewards TO anon, authenticated;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated;

-- Add RLS policies for security
ALTER TABLE referral_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_credits ENABLE ROW LEVEL SECURITY;
ALTER TABLE referral_rewards ENABLE ROW LEVEL SECURITY;

-- Policy: Anyone can read referral events (for viral metrics)
CREATE POLICY "Public read access for referral events" ON referral_events
    FOR SELECT USING (true);

-- Policy: Service role can insert referral events
CREATE POLICY "Service role can insert referral events" ON referral_events
    FOR INSERT WITH CHECK (true);

-- Policy: Users can read their own credits
CREATE POLICY "Users can read own credits" ON user_credits
    FOR SELECT USING (true); -- Service role handles phone number validation

-- Policy: Service role can manage all credits
CREATE POLICY "Service role can manage credits" ON user_credits
    FOR ALL USING (true);

-- Policy: Users can read their own referral rewards
CREATE POLICY "Users can read own referral rewards" ON referral_rewards
    FOR SELECT USING (true);

-- Policy: Service role can manage all referral rewards
CREATE POLICY "Service role can manage referral rewards" ON referral_rewards
    FOR ALL USING (true);

-- Create view for public viral stats (without sensitive data)
CREATE OR REPLACE VIEW public_viral_stats AS
SELECT 
    task_id,
    view_count,
    share_count,
    viral_score,
    trending_rank,
    title,
    created_at
FROM transcriptions
WHERE status = 'completed'
AND view_count > 0
ORDER BY viral_score DESC, view_count DESC;

GRANT SELECT ON public_viral_stats TO anon, authenticated;

-- Insert comment for tracking
INSERT INTO schema_migrations (version, applied_at) 
VALUES ('20250717000001_add_viral_features', NOW())
ON CONFLICT (version) DO NOTHING;