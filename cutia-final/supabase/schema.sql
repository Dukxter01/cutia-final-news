-- Cutia Clasei · rulează în Supabase → SQL Editor → Run (se poate rula din nou fără grijă).
-- Creează locul unde stau datele aplicației, funcțiile de citire/scriere și bucket-ul privat.

-- 1. Datele: câte un rând pentru fiecare colecție (questions, submissions, proposals, ...)
create table if not exists public.cutia_state (
  name text primary key,
  data jsonb not null,
  updated_at timestamptz not null default now()
);
-- Versiunea fiecărui rând: așa știm dacă altă copie a serverului (Vercel) a scris între timp
alter table public.cutia_state add column if not exists version bigint not null default 1;

-- Row Level Security pornit și NICIO politică: cheia publică (anon) din browser
-- nu poate citi sau scrie nimic aici. Doar serverul aplicației, cu cheia secretă,
-- are acces; regulile de acces (ce vede fiecare student) le verifică src/app.py.
alter table public.cutia_state enable row level security;
revoke all on table public.cutia_state from anon, authenticated;

-- 2. Citire: versiunile tuturor colecțiilor + datele doar pentru cele schimbate
--    față de ce are deja serverul (known = {"questions": 12, ...}).
create or replace function public.cutia_sync(known jsonb)
returns table (name text, version bigint, changed boolean, data jsonb)
language sql stable security definer set search_path = public
as $$
  select s.name, s.version,
         (known ->> s.name) is null or (known ->> s.name)::bigint <> s.version,
         case when (known ->> s.name) is null or (known ->> s.name)::bigint <> s.version then s.data end
  from public.cutia_state s;
$$;

-- 3. Scriere: totul sau nimic. Fiecare colecție se scrie doar dacă versiunea din
--    tabel e cea citită de server; altfel întoarcem conflictul și serverul reia cererea.
create or replace function public.cutia_commit(changes jsonb)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare
  item jsonb;
  cur bigint;
  conflicts text[] := '{}';
  versions jsonb := '{}'::jsonb;
begin
  -- O singură scriere odată (durează milisecunde), ca verificarea să fie sigură
  perform pg_advisory_xact_lock(hashtext('cutia_commit'));
  for item in select value from jsonb_array_elements(changes) loop
    select s.version into cur from public.cutia_state s where s.name = item ->> 'name';
    if coalesce(cur, 0) <> coalesce((item ->> 'version')::bigint, 0) then
      conflicts := conflicts || (item ->> 'name');
    end if;
  end loop;
  if coalesce(array_length(conflicts, 1), 0) > 0 then
    return jsonb_build_object('ok', false, 'conflict', to_jsonb(conflicts));
  end if;
  for item in select value from jsonb_array_elements(changes) loop
    insert into public.cutia_state as s (name, data, version, updated_at)
    values (item ->> 'name', item -> 'data', 1, now())
    on conflict on constraint cutia_state_pkey
      do update set data = excluded.data, version = s.version + 1, updated_at = now()
    returning s.version into cur;
    versions := versions || jsonb_build_object(item ->> 'name', cur);
  end loop;
  return jsonb_build_object('ok', true, 'versions', versions);
end;
$$;

-- Funcțiile le poate rula doar serverul (cheia secretă = rolul service_role)
revoke all on function public.cutia_sync(jsonb) from public, anon, authenticated;
revoke all on function public.cutia_commit(jsonb) from public, anon, authenticated;
grant execute on function public.cutia_sync(jsonb) to service_role;
grant execute on function public.cutia_commit(jsonb) to service_role;

-- 4. Fișierele (teme, capturi de la Demo Day): bucket privat, fără politici publice
insert into storage.buckets (id, name, public, file_size_limit)
values ('cutia-files', 'cutia-files', false, 10485760)
on conflict (id) do nothing;
