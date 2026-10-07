-- Cutia Clasei · rulează o singură dată în Supabase → SQL Editor → Run.
-- Creează locul unde stau datele aplicației și bucket-ul privat pentru fișiere.

-- 1. Datele: câte un rând pentru fiecare colecție (questions, submissions, proposals, ...)
create table if not exists public.cutia_state (
  name text primary key,
  data jsonb not null,
  updated_at timestamptz not null default now()
);

-- Row Level Security pornit și NICIO politică: cheia publică (anon) din browser
-- și utilizatorii logați prin Supabase nu pot citi sau scrie nimic aici.
-- Doar serverul aplicației, cu cheia secretă, are acces; regulile de acces
-- (ce vede fiecare student) le verifică serverul, în src/app.py.
alter table public.cutia_state enable row level security;
revoke all on table public.cutia_state from anon, authenticated;

-- 2. Fișierele (teme, capturi de la Demo Day): bucket privat, fără politici publice
insert into storage.buckets (id, name, public, file_size_limit)
values ('cutia-files', 'cutia-files', false, 10485760)
on conflict (id) do nothing;
