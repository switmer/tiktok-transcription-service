-- Create cost_tracking table for real-time API cost tracking
-- Tracks OpenAI Whisper, RapidAPI, Twilio SMS, and other service costs

CREATE TABLE IF NOT EXISTS cost_tracking (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,

    -- Cost categorization
    cost_type TEXT NOT NULL CHECK (cost_type IN (
        'openai_whisper',      -- Audio transcription
        'openai_gpt',          -- GPT for summaries/quotes
        'rapidapi_tiktok',     -- TikTok video downloads
        'rapidapi_youtube',    -- YouTube transcription
        'rapidapi_instagram',  -- Instagram downloads
        'rapidapi_facebook',   -- Facebook downloads
        'twilio_sms_outbound', -- Outbound SMS
        'twilio_sms_inbound',  -- Inbound SMS
        'anthropic_claude'     -- Claude API calls
    )),

    -- Cost in cents (integer for precision)
    amount_cents INTEGER NOT NULL DEFAULT 0,

    -- Associated user (optional - for per-user analytics)
    user_phone TEXT REFERENCES sms_users(phone_number) ON DELETE SET NULL,

    -- Related task (optional - for per-transcription cost breakdown)
    task_id TEXT,

    -- Metadata for detailed tracking
    metadata JSONB DEFAULT '{}' NOT NULL,
    -- Example metadata:
    -- For whisper: {"duration_seconds": 120, "audio_file_size_bytes": 1024000}
    -- For rapidapi: {"endpoint": "tiktok", "video_id": "123456"}
    -- For twilio: {"message_sid": "SM123", "segments": 2}
    -- For gpt: {"model": "gpt-3.5-turbo", "tokens_used": 500}

    -- Track success/failure
    success BOOLEAN NOT NULL DEFAULT true,
    error_message TEXT
);

-- Indexes for efficient querying
CREATE INDEX idx_cost_tracking_created_at ON cost_tracking(created_at DESC);
CREATE INDEX idx_cost_tracking_cost_type ON cost_tracking(cost_type);
CREATE INDEX idx_cost_tracking_user_phone ON cost_tracking(user_phone);
CREATE INDEX idx_cost_tracking_task_id ON cost_tracking(task_id);

-- Composite index for time-range queries by type
CREATE INDEX idx_cost_tracking_type_date ON cost_tracking(cost_type, created_at DESC);

-- Enable RLS
ALTER TABLE cost_tracking ENABLE ROW LEVEL SECURITY;

-- Policy: Service role can manage all cost records
CREATE POLICY "Service role can manage cost tracking" ON cost_tracking
    FOR ALL USING (current_setting('role') = 'service_role');

-- Comments for documentation
COMMENT ON TABLE cost_tracking IS 'Tracks all API costs for admin analytics and profit calculation';
COMMENT ON COLUMN cost_tracking.amount_cents IS 'Cost in cents (e.g., 60 = $0.60)';
COMMENT ON COLUMN cost_tracking.metadata IS 'Additional details like duration, tokens, segments, etc.';

-- ============================================================
-- Aggregation functions for admin stats
-- ============================================================

-- Get cost summary for a time period
CREATE OR REPLACE FUNCTION get_cost_summary(
    start_date TIMESTAMPTZ DEFAULT NOW() - INTERVAL '30 days',
    end_date TIMESTAMPTZ DEFAULT NOW()
)
RETURNS TABLE (
    cost_type TEXT,
    total_cents BIGINT,
    call_count BIGINT,
    success_count BIGINT,
    avg_cents_per_call NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        ct.cost_type,
        COALESCE(SUM(ct.amount_cents), 0)::BIGINT as total_cents,
        COUNT(*)::BIGINT as call_count,
        COUNT(*) FILTER (WHERE ct.success = true)::BIGINT as success_count,
        ROUND(AVG(ct.amount_cents)::NUMERIC, 2) as avg_cents_per_call
    FROM cost_tracking ct
    WHERE ct.created_at >= start_date
      AND ct.created_at <= end_date
    GROUP BY ct.cost_type
    ORDER BY total_cents DESC;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Get comprehensive admin stats
CREATE OR REPLACE FUNCTION get_admin_stats(
    period TEXT DEFAULT 'month' -- 'day', 'week', 'month', 'all'
)
RETURNS JSON AS $$
DECLARE
    start_date TIMESTAMPTZ;
    result JSON;
    total_revenue_cents BIGINT;
    total_costs_cents BIGINT;
    total_users BIGINT;
    active_users BIGINT;
    new_users BIGINT;
    paid_users BIGINT;
    total_transcriptions BIGINT;
    success_rate NUMERIC;
    cost_breakdown JSON;
    revenue_breakdown JSON;
    trend_data JSON;
BEGIN
    -- Calculate start date based on period
    start_date := CASE period
        WHEN 'day' THEN NOW() - INTERVAL '1 day'
        WHEN 'week' THEN NOW() - INTERVAL '7 days'
        WHEN 'month' THEN NOW() - INTERVAL '30 days'
        WHEN 'all' THEN '1970-01-01'::TIMESTAMPTZ
        ELSE NOW() - INTERVAL '30 days'
    END;

    -- Calculate total costs
    SELECT COALESCE(SUM(amount_cents), 0) INTO total_costs_cents
    FROM cost_tracking
    WHERE created_at >= start_date;

    -- Calculate revenue from credit purchases
    SELECT COALESCE(SUM(
        CASE
            WHEN amount IS NOT NULL THEN (amount * 100)::BIGINT
            ELSE 500 -- Default $5 per purchase
        END
    ), 0) INTO total_revenue_cents
    FROM credit_purchases
    WHERE created_at >= start_date;

    -- User stats
    SELECT COUNT(*) INTO total_users FROM sms_users;

    SELECT COUNT(*) INTO active_users
    FROM sms_users
    WHERE updated_at >= start_date OR created_at >= start_date;

    SELECT COUNT(*) INTO new_users
    FROM sms_users
    WHERE created_at >= start_date;

    SELECT COUNT(DISTINCT phone_number) INTO paid_users
    FROM credit_purchases;

    -- Transcription stats
    SELECT COUNT(*) INTO total_transcriptions
    FROM transcriptions
    WHERE created_at >= start_date;

    SELECT ROUND(
        (COUNT(*) FILTER (WHERE status = 'completed')::NUMERIC /
         NULLIF(COUNT(*), 0)) * 100, 1
    ) INTO success_rate
    FROM transcriptions
    WHERE created_at >= start_date;

    -- Cost breakdown by type
    SELECT json_agg(row_to_json(t)) INTO cost_breakdown
    FROM (
        SELECT
            cost_type,
            SUM(amount_cents) as total_cents,
            COUNT(*) as call_count
        FROM cost_tracking
        WHERE created_at >= start_date
        GROUP BY cost_type
        ORDER BY SUM(amount_cents) DESC
    ) t;

    -- Revenue breakdown
    SELECT json_object_agg(
        COALESCE(transaction_type, 'unknown'),
        total_credits
    ) INTO revenue_breakdown
    FROM (
        SELECT
            transaction_type,
            SUM(credit_change) as total_credits
        FROM credit_transactions
        WHERE created_at >= start_date
          AND credit_change > 0
        GROUP BY transaction_type
    ) t;

    -- Build result JSON
    result := json_build_object(
        'period', period,
        'start_date', start_date,
        'end_date', NOW(),
        'financials', json_build_object(
            'revenue_cents', total_revenue_cents,
            'costs_cents', total_costs_cents,
            'profit_cents', total_revenue_cents - total_costs_cents,
            'margin_percent', CASE
                WHEN total_revenue_cents > 0
                THEN ROUND(((total_revenue_cents - total_costs_cents)::NUMERIC / total_revenue_cents) * 100, 1)
                ELSE 0
            END
        ),
        'users', json_build_object(
            'total', total_users,
            'active', active_users,
            'new', new_users,
            'paid', paid_users,
            'conversion_rate', CASE
                WHEN total_users > 0
                THEN ROUND((paid_users::NUMERIC / total_users) * 100, 1)
                ELSE 0
            END
        ),
        'usage', json_build_object(
            'transcriptions', total_transcriptions,
            'success_rate', COALESCE(success_rate, 0)
        ),
        'cost_breakdown', COALESCE(cost_breakdown, '[]'::JSON),
        'revenue_breakdown', COALESCE(revenue_breakdown, '{}'::JSON)
    );

    RETURN result;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Get trend data for charts
CREATE OR REPLACE FUNCTION get_cost_trends(
    days INTEGER DEFAULT 30
)
RETURNS TABLE (
    date DATE,
    total_costs_cents BIGINT,
    total_revenue_cents BIGINT,
    transcription_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    WITH date_series AS (
        SELECT generate_series(
            (NOW() - (days || ' days')::INTERVAL)::DATE,
            NOW()::DATE,
            '1 day'::INTERVAL
        )::DATE as date
    ),
    daily_costs AS (
        SELECT
            created_at::DATE as date,
            SUM(amount_cents) as costs
        FROM cost_tracking
        WHERE created_at >= NOW() - (days || ' days')::INTERVAL
        GROUP BY created_at::DATE
    ),
    daily_revenue AS (
        SELECT
            created_at::DATE as date,
            SUM(COALESCE(amount * 100, 500))::BIGINT as revenue
        FROM credit_purchases
        WHERE created_at >= NOW() - (days || ' days')::INTERVAL
        GROUP BY created_at::DATE
    ),
    daily_transcriptions AS (
        SELECT
            created_at::DATE as date,
            COUNT(*) as count
        FROM transcriptions
        WHERE created_at >= NOW() - (days || ' days')::INTERVAL
        GROUP BY created_at::DATE
    )
    SELECT
        ds.date,
        COALESCE(dc.costs, 0)::BIGINT as total_costs_cents,
        COALESCE(dr.revenue, 0)::BIGINT as total_revenue_cents,
        COALESCE(dt.count, 0)::BIGINT as transcription_count
    FROM date_series ds
    LEFT JOIN daily_costs dc ON ds.date = dc.date
    LEFT JOIN daily_revenue dr ON ds.date = dr.date
    LEFT JOIN daily_transcriptions dt ON ds.date = dt.date
    ORDER BY ds.date;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant execute permissions
GRANT EXECUTE ON FUNCTION get_cost_summary TO authenticated;
GRANT EXECUTE ON FUNCTION get_admin_stats TO authenticated;
GRANT EXECUTE ON FUNCTION get_cost_trends TO authenticated;
