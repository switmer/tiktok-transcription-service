-- tasks table to store transcription job details
CREATE TABLE tasks (
    task_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES auth.users(id) NULL, -- Optional: If using Supabase user accounts later
    url text NOT NULL,
    status text DEFAULT 'pending',
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    video_id text NULL,
    title text NULL,
    error text NULL,
    thumbnail_url text NULL,
    thumbnail_local_path text NULL,
    transcript_file_path text NULL, -- Store path to the saved transcript file
    callback_url text NULL -- If you use callbacks
);

-- Optional: Trigger to update 'updated_at' timestamp automatically
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
   NEW.updated_at = timezone('utc'::text, now());
   RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_tasks_updated_at BEFORE UPDATE
ON tasks FOR EACH ROW EXECUTE PROCEDURE
update_updated_at_column();


-- api_keys table for service authentication
CREATE TABLE api_keys (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_description text, -- Optional: Description of who/what uses the key
    api_key text UNIQUE NOT NULL,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    is_active boolean DEFAULT true NOT NULL
);

-- Secure the api_keys table: only service_role can read the actual keys
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
-- Allow service role full access (adjust as needed for stricter security later)
CREATE POLICY "Allow service role access" ON api_keys FOR ALL
USING (true)
WITH CHECK (true);

-- Note: You will need to manually insert your first API key using the Supabase SQL editor or CLI with service role access.
-- Example (run separately):
-- INSERT INTO api_keys (api_key, user_description) VALUES ('YOUR_SECURE_API_KEY_HERE', 'Initial service key'); 