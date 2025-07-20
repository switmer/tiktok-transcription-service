# Supabase Migrations

This directory contains all database migrations for the ScribeTok application. These migrations are applied in chronological order based on the timestamp in the filename.

## Migration Order

1. **20250415102900_initial_schema.sql** - Initial transcriptions table
2. **20250415131346_add_transcript_column.sql** - Add transcript text column
3. **20250415173734_rename_tasks_to_transcriptions.sql** - Rename table from tasks to transcriptions
4. **20250717000000_add_sms_support.sql** - SMS integration (user_phone, transcript_jobs, user_messages)
5. **20250717000001_add_viral_features.sql** - Viral sharing features
6. **20250720000000_add_video_url_column.sql** - Direct CDN video URLs
7. **20250720000001_add_sms_users_table.sql** - SMS user management and authentication
8. **20250720000002_add_sms_functions.sql** - SQL functions for SMS features
9. **20250720000003_add_rich_metadata_columns.sql** - Rich video metadata (TikTok/YouTube)
10. **20250720000004_add_account_linking.sql** - Account linking functions

## Key Tables

### `transcriptions`
Main table storing all video transcription data:
- Basic info: `task_id`, `url`, `status`, `title`, `created_at`
- SMS support: `user_phone` for phone-based users
- Rich metadata: `duration`, `like_count`, `channel`, `platform`, etc.
- Direct URLs: `video_url` for CDN streaming

### `sms_users` 
SMS user management for phone-first authentication:
- Phone verification with OTP
- Session tokens for authenticated SMS users
- Transcription count tracking
- Optional linking to Supabase auth users

### `user_messages`
SMS interaction logging:
- All incoming SMS messages
- Command extraction
- Rate limiting support

### `transcript_jobs`
SMS workflow queue:
- Background job processing
- Status tracking
- Error handling

## Key Functions

- `get_sms_user_stats(phone)` - Get user transcription statistics
- `normalize_phone_number(phone)` - Standardize phone format
- `link_sms_user_to_auth(phone, auth_id)` - Link SMS user to web account
- `get_sms_linking_stats(phone)` - Get stats for account linking

## Running Migrations

For local development:
```bash
supabase db reset
```

For production:
```bash
supabase db push
```

## Migration Consolidation (July 2025)

All migrations were consolidated into `/app/supabase/migrations/` from multiple directories:
- `/migrations/` (project root)
- `/supabase/migrations/` (project supabase)
- `/app/supabase/migrations/` (main location)

This ensures all Edge Functions and backend services reference the same database schema.