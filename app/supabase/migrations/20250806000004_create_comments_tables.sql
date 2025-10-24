-- Create comments table for storing TikTok comments (Pro Feature)

CREATE TABLE IF NOT EXISTS video_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES transcriptions(task_id) ON DELETE CASCADE,
    comment_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    text TEXT NOT NULL,
    author_name TEXT NOT NULL,
    author_username TEXT NOT NULL,
    author_avatar TEXT,
    created_at_timestamp TEXT,
    likes INTEGER DEFAULT 0,
    reply_count INTEGER DEFAULT 0,
    parent_comment_id TEXT,
    provider TEXT,
    raw_data JSONB,
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, comment_id)
);

CREATE INDEX idx_video_comments_task_id ON video_comments(task_id);
CREATE INDEX idx_video_comments_likes ON video_comments(likes DESC);

ALTER TABLE transcriptions 
ADD COLUMN IF NOT EXISTS comments_fetched BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS comments_count INTEGER DEFAULT 0;

ALTER TABLE video_comments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow public read" ON video_comments FOR SELECT USING (true);
CREATE POLICY "Allow service role" ON video_comments FOR ALL TO service_role USING (true);

