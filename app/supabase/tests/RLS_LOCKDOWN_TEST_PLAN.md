# ScribeTok RLS lockdown test plan

This plan is for `20261120150000_lock_down_public_access.sql` and
`rollbacks/20261120150000_lock_down_public_access_rollback.sql`.

Applying the migration to production (Supabase project `eoktsarockavjdsxqhjm`)
needs Steve's explicit yes. A Supabase branch dry run should come first.
Nothing in this change was executed against that project, and no deploy or
environment change is part of it.

## Who uses which key

| Caller | Key | What it touches |
| --- | --- | --- |
| FastAPI `app/database.py` | `SUPABASE_SERVICE_KEY` (service role) | All tables the API writes: transcriptions, sms_users, user_messages, transcript jobs, credits, referrals, comments, conversation threads, `api_keys` for `X-API-Key` checks |
| Edge `sms-inbound` | `SUPABASE_SERVICE_ROLE_KEY` | `user_messages`, `sms_users`, `transcriptions`; RPCs `request_otp`, `verify_otp`, `safe_message_log`, `get_sms_user_stats`, `link_tiktok_profile`, `get_user_creator_stats`, `atomic_credit_transaction` |
| Edge `sms-status-callback` | `SUPABASE_SERVICE_ROLE_KEY` | `user_messages` delivery fields |
| Edge `update-transcription` | `SUPABASE_SERVICE_ROLE_KEY` | RPC `update_transcription` |
| Edge `twilio-error-webhook` | `SUPABASE_SERVICE_ROLE_KEY` | `twilio_error_logs`, `sms_users` |
| Edge `transcribe-proxy` | no Supabase key | Forwards to FastAPI with server-side `API_KEY`. It does not query Postgres |
| Web client | anon key + Supabase Auth session | See below |

The older front end is the private repo `switmer/ScribeTok` (Magic Patterns sync, last push 2026-04-18). It creates the Supabase client with the anon key. Auth is email and password (`signInWithPassword` / `signUp`). Direct table calls:

- `transcriptions`: `select('*')` by `task_id` or `user_id`, `insert` / `upsert` / `update` / `delete` with `user_id = auth user id`
- `profiles`: `select('*')`, `insert`, and `update` by `id = auth user id`

That copy calls no RPCs. It does not query `sms_users`, `user_messages`, or `conversation_*`. The live Magic Patterns canvas was not in the OS list that this agent can read (the two "Transcribe" canvases have no Supabase queries). Credit balance, chat threads, and SMS history in this backend are served by FastAPI with the service role (`app/api/chat.py`, `app/api/sms.py`, `app/sms.py`). The new policies still allow a logged-in user to read their own rows if the live UI queries those tables directly.

`service_role` keeps working because Supabase grants it `BYPASSRLS` and this migration also adds `rls_service_role_all` on every public table and leaves its grants in place.

## Local proof already run

Docker is not available in this environment, so `supabase start` could not boot the Supabase stack. The same rules were applied on local PostgreSQL 16 with the Supabase roles `anon`, `authenticated`, and `service_role`, `auth.uid()` / `auth.jwt()` reading `request.jwt.claims`, and seed data for two users.

```bash
app/supabase/tests/rls_lockdown_test.sh
```

That script loads `tests/rls_lockdown_fixture.sql`, applies the migration, runs `tests/rls_lockdown_assert.sql`, applies the rollback, and runs `tests/rls_lockdown_assert_rollback.sql`.

Checked after the migration:

- anon `SELECT` on `user_messages`, `api_keys`, `transcriptions`, `sms_users`, `schema_cache`, `sms_job_status`, and `video_comments` is permission denied
- anon `TRUNCATE` on `user_messages` is permission denied
- authenticated `TRUNCATE` on `transcriptions` is permission denied
- anon `SELECT` on `public_transcriptions` returns only the completed public row, and the view has no `user_phone`, `user_id`, `callback_url`, file path, or metadata columns
- user A sees 2 transcriptions (one by `user_id`, one by phone) and none of user B's
- user A sees only their SMS message, thread, video stat, TikTok snapshot, credit ledger row, purchase, and profile
- user A can read `credits_remaining` and cannot read `otp_hash` or update `credits_remaining`
- user A cannot update `profiles.credits`
- user B cannot update or delete user A's transcription, and cannot insert into user A's chat thread
- user B can insert their own profile and transcription, and can append to their own thread
- anon and authenticated cannot execute `atomic_credit_transaction`, `request_otp`, or `fulfill_sms_credit_purchase`
- with `BYPASSRLS` turned off, service_role can still read `api_keys` and `user_messages`, insert an inbound SMS row, deduct a credit, fulfill a Stripe-style purchase, and call `update_transcription`
- `atomic_credit_transaction` has `search_path=public`

Checked after the rollback: anon can again read every `user_messages`, `api_keys`, and `transcriptions` row and can execute `request_otp` and `atomic_credit_transaction`. `fulfill_sms_credit_purchase` stays service_role-only, matching production before this change.

## Supabase branch dry run (do this before production)

1. Create a branch of project `eoktsarockavjdsxqhjm`. Do not merge it.
2. Apply only `20261120150000_lock_down_public_access.sql` to that branch.
3. Repeat the role checks below with the branch URL. Use a throwaway auth user, not a real customer token.
4. Hit the FastAPI health path that validates `X-API-Key` (`api_keys` via the service key) and one SMS inbound fixture if a Twilio test number is available.
5. Only after that, and only with Steve's explicit yes, apply the same file to production. Keep the rollback file ready.

`supabase start` on a machine with Docker is the other local path:

```bash
cd app
supabase start
supabase db reset
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" \
  -f supabase/tests/rls_lockdown_fixture.sql
```

`db reset` already applies the migration. Skip the fixture if you only want the repo schema; the fixture is a production-shaped subset for the assertions. Then run `rls_lockdown_assert.sql` only after loading the fixture into a database that has just had the migration applied. Do not point those commands at the hosted project.

## Browser calls that can break, and how to check

Open the live site, filter the network panel for `rest/v1/` and `rpc/`, once logged out and once logged in.

| If the browser does this | Result after the migration | What to change |
| --- | --- | --- |
| `transcriptions?select=*` with no owner filter, or by `task_id` for someone else's row | Zero rows. Public pages that read the base table go blank | Read `public_transcriptions` for completed public rows, or keep using FastAPI `/api/public/...` (service role) |
| `profiles?id=eq.<auth uid>` select / insert | Works when `id` is `auth.uid()` and `email` matches the JWT | The older client also sends `is_pro` and `usage_limit`. Those columns are not on the production `profiles` table today |
| `profiles` update of `credits` | Permission denied. `email` and `updated_at` can be updated | Credits stay service-role writes |
| `sms_users?select=*` | Permission denied, because OTP and session columns are not granted | Select explicit columns (`credits_remaining`, `phone_number`, `display_name`, `referral_code`, …). Do not request `otp_hash`, `verification_code`, or `session_token` |
| `sms_users` update of `credits_remaining` | Permission denied | Use the service-role credit RPCs from FastAPI |
| `user_messages`, `api_keys`, `schema_cache`, `cost_tracking`, `twilio_error_logs`, `pending_referrals` | Anon denied. Authenticated sees only their own `user_messages` rows, and nothing on the others | Leave these on the service role |
| `conversation_threads` / `conversation_messages` | Own phone only. FastAPI chat uses the service role and is unchanged | A direct browser query must be logged in and linked to `sms_users` by `auth_user_id`, JWT phone, or JWT email |
| `video_comments` or `comments_fetch_progress` for a video the user does not own | Zero rows for authenticated, denied for anon | Public comment lists should go through FastAPI |
| RPC `atomic_credit_transaction`, `request_otp`, `verify_otp`, `use_credit`, `update_transcription`, `get_admin_stats`, `get_cost_trends`, `get_sms_user_stats`, `get_user_creator_stats`, `link_tiktok_profile`, `link_sms_user_to_auth`, `search_transcriptions` | Permission denied for anon and authenticated | The ScribeTok client does not call these. FastAPI and the edge functions call them with the service role |

Production today has no `transcriptions.user_id` values and no `sms_users.auth_user_id` links (0 of 571 transcriptions, 0 of 18 SMS users). A logged-in email user will not see historical SMS transcripts until `link_sms_user_to_auth` has been run for them (FastAPI `app/api/sms.py` does this with the service role). Phone-claim and email-claim policies are in place for when that link exists. All 571 current transcriptions are `visibility = public`, and 364 completed rows carry `user_phone`. Those phones are no longer readable through the anon key; the public view omits them.

## Rollback

Run `rollbacks/20261120150000_lock_down_public_access_rollback.sql` on the same database that received the migration. It restores the previous open policies (including `api_keys` `USING (true)` and `transcriptions` "Public can view all transcriptions"), turns RLS back off on the eight tables that had it off, and restores anon/authenticated `GRANT ALL` plus function execute. It does not grant `fulfill_sms_credit_purchase` back to anon; that function was already service_role-only.

Take a fresh branch or a logical backup before the production apply so the rollback is not the only way back.
