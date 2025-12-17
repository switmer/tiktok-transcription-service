-- Add monthly usage tracking back to sms_users if it's missing in production.
-- This is safe to run even if the column already exists.

alter table public.sms_users
  add column if not exists monthly_transcriptions integer default 0;

comment on column public.sms_users.monthly_transcriptions
  is 'Number of transcriptions this month (incremented by sms-inbound; reset policy is app-defined)';


