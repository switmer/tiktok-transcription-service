-- Create table for Twilio error logs
CREATE TABLE IF NOT EXISTS twilio_error_logs (
    id BIGSERIAL PRIMARY KEY,
    twilio_sid TEXT NOT NULL,
    account_sid TEXT NOT NULL,
    parent_account_sid TEXT,
    timestamp TIMESTAMPTZ NOT NULL,
    level TEXT NOT NULL CHECK (level IN ('error', 'warning')),
    payload_type TEXT NOT NULL DEFAULT 'application/json',
    payload_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed BOOLEAN DEFAULT FALSE
);

-- Create indexes for efficient querying
CREATE INDEX idx_twilio_error_logs_timestamp ON twilio_error_logs(timestamp DESC);
CREATE INDEX idx_twilio_error_logs_level ON twilio_error_logs(level);
CREATE INDEX idx_twilio_error_logs_created_at ON twilio_error_logs(created_at DESC);
CREATE INDEX idx_twilio_error_logs_processed ON twilio_error_logs(processed) WHERE NOT processed;

-- Add RLS policy
ALTER TABLE twilio_error_logs ENABLE ROW LEVEL SECURITY;

-- Policy for service role (Edge Functions can insert/read)
CREATE POLICY "Service role can manage twilio_error_logs" ON twilio_error_logs
    FOR ALL USING (auth.role() = 'service_role');

-- Add comment
COMMENT ON TABLE twilio_error_logs IS 'Stores Twilio error and warning webhooks for monitoring and debugging SMS delivery issues';