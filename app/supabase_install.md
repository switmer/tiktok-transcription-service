
Okay, integrating Supabase is a great move for making the service more robust and scalable! It will give you persistent storage for task data (instead of the current in-memory dictionary) and a proper authentication system.

Here's a plan to get Supabase integrated:

1.  **Install Supabase Client Library:** We'll add the `supabase-py` library to your `requirements.txt`.
2.  **Set up Supabase Project:** You'll need to create a free project on [supabase.com](https://supabase.com). This will give you:
    *   A Postgres database.
    *   API URLs.
    *   API Keys (`anon` key and `service_role` key).
3.  **Database Schema:** We'll define the necessary database tables. For this service, we'll primarily need:
    *   A `tasks` table to store information about each transcription job (replacing the current `tasks` dictionary).
    *   An `api_keys` table to store valid API keys that can access protected endpoints (replacing the single `API_KEY` environment variable).
4.  **Supabase CLI (Recommended):** Using the Supabase CLI is highly recommended for managing your database schema (creating tables, applying changes) locally and syncing with your Supabase project. You'll need to install it ([Supabase CLI Docs](https://supabase.com/docs/guides/cli)).
5.  **Apply Schema:** Use the Supabase CLI to create the tables in your local and remote Supabase database.
6.  **Update Backend Code (`app.py`):**
    *   Add code to initialize the `supabase-py` client using credentials stored in environment variables.
    *   Modify all functions currently interacting with the `tasks` dictionary (`init_task`, `get_task`, `list_tasks`, `delete_task`, `update_task_status`, etc.) to query/insert/update the `tasks` table in Supabase instead.
    *   Update the `verify_api_key` function to check the provided key against the `api_keys` table in Supabase.
7.  **Environment Variables:** Add your Supabase URL and keys (`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`) to your `.env` file locally and to your Render service's environment variables.

Let's start with the database schema.

**Proposed Database Schema (SQL):**

```sql
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
    -- Add other fields from your TranscriptionResponse model as needed
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
CREATE POLICY "Allow service role access" ON api_keys FOR SELECT USING (true);
CREATE POLICY "Allow service role insert" ON api_keys FOR INSERT WITH CHECK (true);
-- Add policies for update/delete as needed, restricting appropriately

-- Insert your initial API key (replace 'YOUR_INITIAL_API_KEY' with a secure random string)
-- You'll need to run this using your service_role key or via SQL editor in Supabase dashboard
-- INSERT INTO api_keys (api_key, user_description) VALUES ('YOUR_INITIAL_API_KEY', 'Initial service key');

```

**Next Steps:**

1.  **Create Supabase Project:** Go to [supabase.com](https://supabase.com) and create a new project. Note down your project URL, `anon` key, and `service_role` key.
2.  **Install Supabase CLI:** Follow the instructions [here](https://supabase.com/docs/guides/cli) to install the CLI.
3.  **Login & Link:** Run `supabase login` and then `supabase link --project-ref <your-project-ref>` (find project-ref in your Supabase project settings) in your `app` directory.
4.  **Create Migration File:** Save the SQL schema above into a new file within your `app` directory, inside a `supabase/migrations` folder (the CLI might create this for you). For example: `app/supabase/migrations/YYYYMMDDHHMMSS_initial_schema.sql`.
5.  **Apply Migration Locally (Optional but recommended):** Run `supabase start` (if you haven't already) to spin up a local Supabase instance, then run `supabase db push` or `supabase migration up` to apply the schema to your local instance.
6.  **Apply Migration Remotely:** Run `supabase migration up` to apply the schema to your actual Supabase project database.

Once you've completed these setup steps, let me know, and we can proceed with:

*   Adding `supabase-py` to `requirements.txt`.
*   Modifying the Python code in `app.py` to use Supabase.
