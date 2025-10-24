-- Create twilio_error_logs table for tracking Twilio webhook errors and warnings

CREATE TABLE IF NOT EXISTS twilio_error_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twilio_sid TEXT NOT NULL,
    account_sid TEXT NOT NULL,
    parent_account_sid TEXT,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL CHECK (level IN ('error', 'warning')),
    payload_type TEXT,
    payload_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Add indexes for faster lookups
CREATE INDEX IF NOT EXISTS idx_twilio_error_logs_twilio_sid ON twilio_error_logs(twilio_sid);
CREATE INDEX IF NOT EXISTS idx_twilio_error_logs_level ON twilio_error_logs(level);
CREATE INDEX IF NOT EXISTS idx_twilio_error_logs_created_at ON twilio_error_logs(created_at DESC);

-- Add trigger for updated_at
CREATE TRIGGER update_twilio_error_logs_updated_at
    BEFORE UPDATE ON twilio_error_logs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Add RLS policies (allow service role to insert)
ALTER TABLE twilio_error_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow service role full access to twilio_error_logs"
    ON twilio_error_logs
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Created twilio_error_logs table for tracking SMS delivery issues';
    RAISE NOTICE 'This table will log Twilio errors and warnings from the error webhook.';
END $$;

