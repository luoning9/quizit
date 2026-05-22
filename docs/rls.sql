-- Basic RLS for quizit
-- Assumptions:
-- - Public decks are readable by everyone when `decks.is_public = true` and `is_deleted = false`.
-- - Only the owner can create/update/delete their own decks and cards.
-- - User progress data stays private to the owning user.
-- - This file is meant to be applied after the base schema exists.

begin;

-- Decks
alter table public.decks enable row level security;

drop policy if exists "decks_select_public_or_owner" on public.decks;
create policy "decks_select_public_or_owner"
on public.decks
for select
to anon, authenticated
using (
    is_deleted = false
    and (
        is_public = true
        or owner_id = auth.uid()
    )
);

drop policy if exists "decks_insert_owner_only" on public.decks;
create policy "decks_insert_owner_only"
on public.decks
for insert
to authenticated
with check (
    owner_id = auth.uid()
);

drop policy if exists "decks_update_owner_only" on public.decks;
create policy "decks_update_owner_only"
on public.decks
for update
to authenticated
using (
    owner_id = auth.uid()
)
with check (
    owner_id = auth.uid()
);

drop policy if exists "decks_delete_owner_only" on public.decks;
create policy "decks_delete_owner_only"
on public.decks
for delete
to authenticated
using (
    owner_id = auth.uid()
);

-- Cards
alter table public.cards enable row level security;

drop policy if exists "cards_select_anyone" on public.cards;
create policy "cards_select_anyone"
on public.cards
for select
to anon, authenticated
using (
    true
);

drop policy if exists "cards_insert_owner_only" on public.cards;
create policy "cards_insert_owner_only"
on public.cards
for insert
to authenticated
with check (
    owner_id = auth.uid()
);

drop policy if exists "cards_update_owner_only" on public.cards;
create policy "cards_update_owner_only"
on public.cards
for update
to authenticated
using (
    owner_id = auth.uid()
)
with check (
    owner_id = auth.uid()
);

drop policy if exists "cards_delete_owner_only" on public.cards;
create policy "cards_delete_owner_only"
on public.cards
for delete
to authenticated
using (
    owner_id = auth.uid()
);

-- Card reviews
alter table public.card_reviews enable row level security;

drop policy if exists "card_reviews_owner_only" on public.card_reviews;
create policy "card_reviews_owner_only"
on public.card_reviews
for all
to authenticated
using (
    user_id = auth.uid()
)
with check (
    user_id = auth.uid()
);

-- Card stats
alter table public.card_stats enable row level security;

drop policy if exists "card_stats_owner_only" on public.card_stats;
create policy "card_stats_owner_only"
on public.card_stats
for all
to authenticated
using (
    user_id = auth.uid()
)
with check (
    user_id = auth.uid()
);

-- Quizzes
alter table public.quizzes enable row level security;

drop policy if exists "quizzes_owner_only" on public.quizzes;
create policy "quizzes_owner_only"
on public.quizzes
for all
to authenticated
using (
    owner_id = auth.uid()
)
with check (
    owner_id = auth.uid()
);

-- Quiz runs
alter table public.quiz_runs enable row level security;

drop policy if exists "quiz_runs_owner_only" on public.quiz_runs;
create policy "quiz_runs_owner_only"
on public.quiz_runs
for all
to authenticated
using (
    user_id = auth.uid()
)
with check (
    user_id = auth.uid()
);

-- Profiles
alter table public.profiles enable row level security;

drop policy if exists "profiles_owner_only" on public.profiles;
create policy "profiles_owner_only"
on public.profiles
for all
to authenticated
using (
    id = auth.uid()
)
with check (
    id = auth.uid()
);

commit;
