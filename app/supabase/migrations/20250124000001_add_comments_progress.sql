-- Create comments_fetch_progress table for tracking comment fetching progress
-- This table tracks the progress of fetching ALL comments for a video

CREATE TABLE IF NOT EXISTS comments_fetch_progress (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID REFERENCES transcriptions(task_id),
    video_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('in_progress', 'completed', 'failed')),
    current_page INTEGER DEFAULT 0,
    total_pages_estimate INTEGER,
    comments_fetched INTEGER DEFAULT 0,
    provider TEXT,
    started_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    error_message TEXT,
    UNIQUE(task_id)
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_comments_progress_task_id ON comments_fetch_progress(task_id);
CREATE INDEX IF NOT EXISTS idx_comments_progress_status ON comments_fetch_progress(status);
CREATE INDEX IF NOT EXISTS idx_comments_progress_video_id ON comments_fetch_progress(video_id);

-- Enable Row Level Security
ALTER TABLE comments_fetch_progress ENABLE ROW LEVEL SECURITY;

-- Create policies for access control
CREATE POLICY "Allow public read" ON comments_fetch_progress FOR SELECT USING (true);
CREATE POLICY "Allow service role" ON comments_fetch_progress FOR ALL TO service_role USING (true);

-- Add trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_comments_fetch_progress_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_comments_fetch_progress_updated_at
    BEFORE UPDATE ON comments_fetch_progress
    FOR EACH ROW
    EXECUTE FUNCTION update_comments_fetch_progress_updated_at();
