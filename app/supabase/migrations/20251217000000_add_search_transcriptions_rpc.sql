-- Ensure pg_trgm is available for similarity() and trigram operators
create extension if not exists pg_trgm;

-- Optional supporting indexes for common filters + ordering
create index if not exists idx_transcriptions_updated_at
on public.transcriptions(updated_at);

create index if not exists idx_transcriptions_visibility_status
on public.transcriptions(visibility, status);

create or replace function public.search_transcriptions(
  query text,
  only_public boolean default true,
  only_completed boolean default true,
  limit_results int default 50,
  offset_results int default 0
) returns table (
  task_id uuid,
  title text,
  updated_at timestamptz,
  rank float4,
  source text
)
language sql
stable
as $$
  with params as (
    select
      trim(query)::text as q,
      websearch_to_tsquery('english', trim(query)) as q_ts
  ),
  title_hits as (
    select
      t.task_id,
      t.title,
      t.updated_at,
      similarity(coalesce(t.title, ''), p.q)::float4 as rank,
      'title'::text as source
    from public.transcriptions t
    join params p on true
    where p.q is not null
      and length(p.q) >= 2
      and t.title is not null
      and t.title ilike '%' || p.q || '%'
      -- Light threshold to reduce noisy matches (tune as desired)
      and similarity(coalesce(t.title, ''), p.q) >= 0.1
      and (not only_public or t.visibility = 'public')
      and (not only_completed or t.status = 'completed')
  ),
  transcript_hits as (
    select
      t.task_id,
      t.title,
      t.updated_at,
      -- Prefer the precomputed FTS vector when available
      ts_rank_cd(
        coalesce(t.fts, to_tsvector('english', coalesce(t.transcript, ''))),
        p.q_ts
      )::float4 as rank,
      'transcript'::text as source
    from public.transcriptions t
    join params p on true
    where p.q is not null
      and length(p.q) >= 2
      and t.transcript is not null
      and t.transcript <> ''
      and coalesce(t.fts, to_tsvector('english', coalesce(t.transcript, '')))
          @@ p.q_ts
      and (not only_public or t.visibility = 'public')
      and (not only_completed or t.status = 'completed')
  )
  select *
  from title_hits
  union all
  select *
  from transcript_hits
  order by rank desc nulls last, updated_at desc, task_id asc
  limit limit_results offset offset_results;
$$;

grant execute on function public.search_transcriptions(text, boolean, boolean, int, int)
  to anon, authenticated;