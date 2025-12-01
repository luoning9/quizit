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

-- Trigger: auto-calc next_due_at and ensure updated_at
create or replace function public.set_card_stats_due()
returns trigger
language plpgsql
as $$
declare
    v_ease    numeric := coalesce(new.ease_factor, 0);
    v_correct int     := greatest(coalesce(new.correct_count, 0), 1);
    v_wrong   int     := greatest(coalesce(new.wrong_count, 0), 1);
    v_days    numeric := 0;
    v_base    timestamptz;
begin
    -- 统一更新时间戳
    new.updated_at := now();
    v_base := new.updated_at;

    if v_ease <= 1.5 then
        v_days := 0.5 / v_wrong;
    elsif v_ease <= 2.5 then
        v_days := 1;
    elsif v_ease <= 3.5 then
        v_days := 3;
    else
        v_days := 7 * v_correct;
    end if;

    new.next_due_at := v_base + (v_days || ' days')::interval;
    return new;
end;
$$;

drop trigger if exists trg_card_stats_due on public.card_stats;
create trigger trg_card_stats_due
before insert or update on public.card_stats
for each row
execute function public.set_card_stats_due();


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

-- 当前用户的测验记录视图
create or replace view public.quiz_runs_user as
select *
from public.quiz_runs
where user_id = auth.uid();


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


CREATE OR REPLACE FUNCTION public.select_practice_cards(_folder_path text, _limit integer, _mode text DEFAULT 'random'::text)
 RETURNS TABLE(card_id uuid, deck_id uuid, deck_title text, front text, back text)
 LANGUAGE sql
AS $function$
WITH decks_in_scope AS (
  SELECT
    d.id,
    d.title,
    d.items
  FROM public.decks d
  WHERE
    -- 根目录：_folder_path 为空时，选所有 deck
    COALESCE(_folder_path, '') = ''
    OR d.title = _folder_path
    OR d.title LIKE _folder_path || '/%'
),
deck_cards AS (
  SELECT
    ds.id AS deck_id,
    ds.title AS deck_title,
    (elem->>'card_id')::uuid AS card_id
  FROM decks_in_scope ds
  CROSS JOIN LATERAL jsonb_array_elements(ds.items->'items') AS elem
)
SELECT
    c.id AS card_id,
    dc.deck_id,
    dc.deck_title,
    c.front,
    c.back
FROM deck_cards dc
         JOIN public.cards c ON c.id = dc.card_id
ORDER BY
    -- ordered 模式：按 deck_id 正序
    CASE
        WHEN _mode = 'ordered' THEN dc.deck_id::text
        ELSE NULL
        END ASC,
    -- reverse 模式：按 deck_id 逆序
    CASE
        WHEN _mode = 'reverse' THEN dc.deck_id::text
        ELSE NULL
        END DESC,
    -- 其它模式：随机
random()
    LIMIT COALESCE(_limit, 20);
$function$

-- 选择练习卡片（Leitner 策略）：优先到期/未建 stats 的卡片，再随机抽取
CREATE OR REPLACE FUNCTION public.select_practice_cards_leitner(
    _folder_path text,
    _limit integer DEFAULT 20,
    _mode text DEFAULT 'random'
)
RETURNS TABLE(card_id uuid, deck_id uuid, deck_title text, front text, back text)
LANGUAGE sql
SECURITY DEFINER
AS $function$
WITH decks_in_scope AS (
    SELECT d.id, d.title, d.items, d.created_at
    FROM public.decks d
    WHERE d.owner_id = auth.uid()
      AND (
            COALESCE(_folder_path, '') = ''
         OR d.title = _folder_path
         OR d.title LIKE _folder_path || '/%'
      )
),
deck_cards AS (
    SELECT
        ds.id AS deck_id,
        ds.title AS deck_title,
        (elem->>'card_id')::uuid AS card_id,
        ds.created_at AS deck_created_at
    FROM decks_in_scope ds
    CROSS JOIN LATERAL jsonb_array_elements(ds.items->'items') AS elem
),
stats_joined AS (
    SELECT
        dc.card_id,
        dc.deck_id,
        dc.deck_title,
        cs.next_due_at,
        cs.user_id
    FROM deck_cards dc
    LEFT JOIN public.card_stats cs
        ON cs.card_id = dc.card_id
       AND cs.user_id = auth.uid()
    WHERE cs.card_id IS NULL OR cs.next_due_at <= now() + interval '2 days'
),
due_cards AS (
    SELECT row_number() OVER (ORDER BY COALESCE(next_due_at, now()) ASC) AS seq,
           card_id, deck_id, deck_title
    FROM stats_joined
    WHERE user_id IS NOT NULL
    ORDER BY COALESCE(next_due_at, now()) ASC
    LIMIT 100
),
new_cards AS (
    SELECT row_number() OVER (ORDER BY dc.deck_created_at ASC) AS seq,
           dc.card_id, dc.deck_id, dc.deck_title
    FROM deck_cards dc
    WHERE NOT EXISTS (
        SELECT 1 FROM public.card_stats cs
        WHERE cs.card_id = dc.card_id AND cs.user_id = auth.uid()
    )
    ORDER BY dc.deck_created_at ASC
    LIMIT 100
),
pool AS (
    SELECT card_id, deck_id, deck_title, seq
    FROM due_cards
    UNION ALL
    SELECT card_id, deck_id, deck_title, seq
    FROM new_cards
)
SELECT
    c.id AS card_id,
    p.deck_id,
    p.deck_title,
    c.front,
    c.back
FROM pool p
JOIN public.cards c ON c.id = p.card_id
ORDER BY
    CASE WHEN _mode = 'ordered' THEN p.seq ELSE NULL END ASC,
    CASE WHEN _mode = 'random' THEN random() ELSE NULL END
LIMIT COALESCE(_limit, 20);
$function$
