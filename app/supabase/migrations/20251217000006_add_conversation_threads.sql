create extension if not exists pgcrypto;

create table if not exists public.conversation_threads (
  id uuid primary key default gen_random_uuid(),
  user_phone text not null,
  task_id uuid not null,
  summary text,
  message_count int not null default 0,
  status text not null default 'active',
  last_active timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  closed_at timestamptz
);

create index if not exists conversation_threads_user_phone_idx
  on public.conversation_threads (user_phone);

create unique index if not exists conversation_threads_active_phone_idx
  on public.conversation_threads (user_phone)
  where status = 'active';

create table if not exists public.conversation_messages (
  id uuid primary key default gen_random_uuid(),
  thread_id uuid not null references public.conversation_threads(id) on delete cascade,
  role text not null,
  content text not null,
  created_at timestamptz not null default now()
);

create index if not exists conversation_messages_thread_idx
  on public.conversation_messages (thread_id, created_at);
