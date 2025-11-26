create table public.card_reviews (
                                     id uuid not null default gen_random_uuid (),
                                     user_id uuid not null default auth.uid(),
                                     card_id uuid not null,
                                     reviewed_at timestamp with time zone null default now(),
                                     user_answer text null,
                                     is_correct boolean null,
                                     time_spent integer null,
                                     meta jsonb null,
                                     constraint card_reviews_pkey primary key (id),
                                     constraint card_reviews_card_id_fkey foreign KEY (card_id) references cards (id) on delete CASCADE,
                                     constraint card_reviews_user_id_fkey foreign KEY (user_id) references auth.users (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists idx_card_reviews_user on public.card_reviews using btree (user_id) TABLESPACE pg_default;

create index IF not exists idx_card_reviews_card on public.card_reviews using btree (card_id) TABLESPACE pg_default;

create index IF not exists idx_card_reviews_time on public.card_reviews using btree (reviewed_at) TABLESPACE pg_default;


create table public.card_stats (
                                   id uuid not null default gen_random_uuid (),
                                   user_id uuid not null default auth.uid(),
                                   card_id uuid not null,
                                   last_reviewed_at timestamp with time zone null,
                                   review_count integer null default 0,
                                   correct_count integer null default 0,
                                   wrong_count integer null default 0,
                                   ease_factor numeric(4, 2) null,
                                   next_due_at timestamp with time zone null,
                                   created_at timestamp with time zone null default now(),
                                   updated_at timestamp with time zone null default now(),
                                   constraint card_stats_pkey primary key (id),
                                   constraint card_stats_user_id_card_id_key unique (user_id, card_id),
                                   constraint card_stats_card_id_fkey foreign KEY (card_id) references cards (id) on delete CASCADE,
                                   constraint card_stats_user_id_fkey foreign KEY (user_id) references auth.users (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists idx_card_stats_user on public.card_stats using btree (user_id) TABLESPACE pg_default;

create index IF not exists idx_card_stats_due on public.card_stats using btree (next_due_at) TABLESPACE pg_default;


create table public.cards (
                              id uuid not null default gen_random_uuid (),
                              owner_id uuid not null default auth.uid(),
                              front text not null,
                              back text not null,
                              card_type public.card_type_enum null default 'basic'::card_type_enum,
                              explanation text null,
                              meta jsonb null,
                              created_at timestamp with time zone null default now(),
                              updated_at timestamp with time zone null default now(),
                              constraint cards_pkey primary key (id),
                              constraint cards_owner_id_fkey foreign KEY (owner_id) references auth.users (id) on delete cascade
) TABLESPACE pg_default;

create index IF not exists idx_cards_owner on public.cards using btree (owner_id) TABLESPACE pg_default;


create view public.deck_folder_stats as
with
    base as (
        select
            d.id as deck_id,
            d.title,
            d.items,
            COALESCE(jsonb_array_length(d.items -> 'items'::text), 0) as item_count
        from
            decks d
        where
            d.title is not null
          and btrim(d.title) <> ''::text
          and d.owner_id = auth.uid()
        ),
        deck_cards as (
        select
        b.deck_id,
        (elem.value ->> 'card_id'::text)::uuid as card_id
        from
        base b
        cross join lateral jsonb_array_elements(b.items -> 'items'::text) elem (value)
        ),
        card_ease as (
        select
        dc.deck_id,
        dc.card_id,
        case
        when cs.review_count > 0 then cs.ease_factor
        else 0::numeric
        end as ef
        from
        deck_cards dc
        left join card_stats cs on cs.card_id = dc.card_id and cs.user_id = auth.uid()
        ),
        deck_ease as (
        select
        card_ease.deck_id,
        sum(card_ease.ef) as ease_sum
        from
        card_ease
        group by
        card_ease.deck_id
        ),
        paths as (
        select
        b.deck_id,
        b.item_count,
        COALESCE(e.ease_sum, 0::numeric) as ease_sum,
        regexp_split_to_array(b.title, '/'::text) as parts
        from
        base b
        left join deck_ease e on e.deck_id = b.deck_id
        ),
        prefixes as (
        select
        paths.deck_id,
        paths.item_count,
        paths.ease_sum,
        array_to_string(paths.parts[1:s.i], '/'::text) as path
        from
        paths,
        lateral generate_subscripts(paths.parts, 1) s (i)
        )
select
    path,
    (
        select
            d.id
        from
            decks d
        where
            d.title = p.path
          and d.owner_id = auth.uid()
        limit 1
    ) as deck_id,
  count(distinct deck_id) as deck_count,
  sum(item_count) as total_items,
  sum(ease_sum) as total_ease_factor,
  (
    exists (
      select
        1
      from
        decks d
      where
        d.title = p.path
        and d.owner_id = auth.uid()
    )
  ) as is_deck
from
    prefixes p
group by
    path
order by
    path;


create table public.decks (
                              id uuid not null default gen_random_uuid (),
                              owner_id uuid not null default auth.uid(),
                              title text not null,
                              description text null,
                              subject text null,
                              grade text null,
                              tags text[] null default '{}'::text[],
                              is_public boolean null default false,
                              items jsonb not null default '{"items": []}'::jsonb,
                              created_at timestamp with time zone null default now(),
                              updated_at timestamp with time zone null default now(),
                              constraint decks_pkey primary key (id),
                              constraint decks_owner_id_fkey foreign KEY (owner_id) references auth.users (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists idx_decks_owner on public.decks using btree (owner_id) TABLESPACE pg_default;

create index IF not exists idx_decks_tags on public.decks using gin (tags) TABLESPACE pg_default;


create table public.profiles (
                                 id uuid not null,
                                 created_at timestamp with time zone null default now(),
                                 display_name text null,
                                 role text null default 'student'::text,
                                 extra jsonb null,
                                 constraint profiles_pkey primary key (id),
                                 constraint profiles_id_fkey foreign KEY (id) references auth.users (id) on delete CASCADE
) TABLESPACE pg_default;


create table public.quiz_runs (
                                  id uuid not null default gen_random_uuid (),
                                  template_id uuid null,
                                  user_id uuid not null default auth.uid(),
                                  started_at timestamp with time zone null default now(),
                                  finished_at timestamp with time zone null,
                                  score numeric(5, 2) null,
                                  total_items integer null,
                                  correct_items integer null,
                                  config jsonb null,
                                  created_at timestamp with time zone null default now(),
                                  constraint quizzes_pkey primary key (id),
                                  constraint quizzes_template_id_fkey foreign KEY (template_id) references quiz_templates (id) on delete set null,
                                  constraint quizzes_user_id_fkey foreign KEY (user_id) references auth.users (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists idx_quiz_runs_user on public.quiz_runs using btree (user_id) TABLESPACE pg_default;

create index IF not exists idx_quiz_runs_template on public.quiz_runs using btree (template_id) TABLESPACE pg_default;


create view public.quiz_template_stats as
select
    qt.id,
    qt.owner_id,
    qt.title,
    qt.description,
    qt.mode,
    qt.deck_name,
    COALESCE(jsonb_array_length(qt.items -> 'items'::text), 0) as item_count,
    qt.created_at,
    COALESCE(qs.attempt_count, 0::bigint) as attempt_count,
    qs.last_attempt_at,
    qs.last_score
from
    quiz_templates qt
        left join (
        select
            qr_outer.template_id,
            count(*) as attempt_count,
            max(qr_outer.finished_at) as last_attempt_at,
            (
                select
                    qr.score
                from
                    quiz_runs qr
                where
                    qr.template_id = qr_outer.template_id
                      and qr.user_id = auth.uid()
                order by
                    qr.finished_at desc nulls last
                limit
            1
    ) as last_score
    from
      quiz_runs qr_outer
    where qr_outer.user_id = auth.uid()
    group by
      qr_outer.template_id
  ) qs on qs.template_id = qt.id
where qt.owner_id = auth.uid()
order by
  qt.created_at desc;


create table public.quiz_templates (
                                       id uuid not null default gen_random_uuid (),
                                       owner_id uuid not null default auth.uid(),
                                       title text not null,
                                       description text null,
                                       mode public.quiz_mode_enum null default 'mixed'::quiz_mode_enum,
                                       items jsonb not null default '{"items": []}'::jsonb,
                                       config jsonb null,
                                       created_at timestamp with time zone null default now(),
                                       updated_at timestamp with time zone null default now(),
                                       deck_name text null,
                                       constraint quiz_templates_pkey primary key (id),
                                       constraint quiz_templates_owner_id_fkey foreign KEY (owner_id) references auth.users (id) on delete cascade
) TABLESPACE pg_default;

create index IF not exists idx_quiz_templates_owner on public.quiz_templates using btree (owner_id) TABLESPACE pg_default;
