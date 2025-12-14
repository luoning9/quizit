create table public.card_reviews (
                                     id uuid not null default gen_random_uuid (),
                                     user_id uuid not null default auth.uid(),
                                     card_id uuid not null,
                                     reviewed_at timestamp with time zone null default now(),
                                     user_answer text null,
                                     is_correct boolean null,
                                     time_spent integer null,
                                     is_question boolean not null default false,
                                     belongs_to uuid null,
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

create index IF not exists idx_decks_owner_title on public.decks using btree (owner_id, title) TABLESPACE pg_default;

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

-- 随机获取匹配前缀的卡片
create or replace function public.select_cards_by_path(
    in _path text,
    in _limit int default 100,
    in _mode text default 'random'
)
returns table(card_id uuid, front text, back text)
language sql
security definer
as $$
    with params as (
        select
            coalesce(nullif(trim(_path), ''), '') as path,
            least(greatest(coalesce(_limit, 100), 1), 500) as lim
    )
    select v.card_id, c.front, c.back
    from user_card_stats_view v
    join public.cards c on c.id = v.card_id
    cross join params p
    where v.deck_name = p.path
       or v.deck_name ilike p.path || '/%'
    order by random()
    limit (select lim from params);
$$;

grant execute on function public.select_cards_by_path(text,int,text) to anon, authenticated;


create or replace view public.user_deck_folder_view as
with
    base as (
        select
            d.id as deck_id,
            d.title,
            d.items,
            COALESCE(jsonb_array_length(d.items -> 'items'::text), 0) as item_count
        from
            user_active_decks d
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
            user_active_decks d
        where
            d.title = p.path
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
        user_active_decks d
      where
        d.title = p.path
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
                              is_deleted boolean not null default false,
                              constraint decks_pkey primary key (id),
                              constraint decks_owner_id_fkey foreign KEY (owner_id) references auth.users (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists idx_decks_owner on public.decks using btree (owner_id) TABLESPACE pg_default;

create index IF not exists idx_decks_tags on public.decks using gin (tags) TABLESPACE pg_default;

create or replace view public.user_active_decks as
select *
from public.decks
where owner_id = auth.uid()
  and is_deleted = false;

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
                                  constraint quizzes_template_id_fkey foreign KEY (template_id) references quizzes (id) on delete set null,
                                  constraint quizzes_user_id_fkey foreign KEY (user_id) references auth.users (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists idx_quiz_runs_user on public.quiz_runs using btree (user_id) TABLESPACE pg_default;

create index IF not exists idx_quiz_runs_template on public.quiz_runs using btree (template_id) TABLESPACE pg_default;

-- 当前用户的测验记录视图
create or replace view public.user_quiz_runs_view as
select *
from public.quiz_runs
where user_id = auth.uid();


create or replace view public.user_quiz_stats_view as
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
    user_active_quizzes qt
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


create table public.quizzes (
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
                                       is_deleted boolean not null default false,
                                       constraint quizzes_pkey primary key (id),
                                       constraint quizzes_owner_id_fkey foreign KEY (owner_id) references auth.users (id) on delete cascade
) TABLESPACE pg_default;

create index IF not exists idx_quizzes_owner on public.quizzes using btree (owner_id) TABLESPACE pg_default;

-- 兼容旧名：提供只读视图 quiz_templates
create or replace view public.quiz_templates as
select * from public.quizzes;

-- 当前用户的未删除测验模板
create or replace view public.user_active_quizzes as
select *
from public.quizzes
where owner_id = auth.uid()
  and is_deleted = false;


CREATE OR REPLACE FUNCTION public.select_practice_cards_leitner(
    _folder_path text,
    _limit integer DEFAULT 20,
    _mode text DEFAULT 'random'
)
RETURNS TABLE(card_id uuid, deck_id uuid, deck_title text, front text, back text)
LANGUAGE sql
SECURITY DEFINER
AS $function$
WITH base AS (
    SELECT *
    FROM public.user_card_stats_view u
    WHERE (
            COALESCE(_folder_path, '') = ''
         OR u.deck_name = _folder_path
         OR u.deck_name LIKE _folder_path || '/%'
    )
),
due_cards AS (
    SELECT
        row_number() OVER (ORDER BY COALESCE(next_due_at, now()) ASC) AS seq,
        card_id,
        deck_id,
        deck_name AS deck_title
    FROM base
    WHERE learned
      AND (next_due_at IS NULL OR next_due_at <= now() + interval '2 days')
    ORDER BY COALESCE(next_due_at, now()) ASC
    LIMIT _limit * 2
),
new_cards AS (
    SELECT
        row_number() OVER (ORDER BY deck_created_at ASC) AS seq,
        card_id,
        deck_id,
        deck_name AS deck_title
    FROM base
    WHERE learned = FALSE
    ORDER BY deck_created_at ASC
    LIMIT _limit * 2
),
pooled AS (
    SELECT card_id, deck_id, deck_title, seq FROM due_cards
    UNION ALL
    SELECT card_id, deck_id, deck_title, seq FROM new_cards
    UNION ALL
    SELECT
        card_id,
        deck_id,
        deck_name AS deck_title,
        row_number() OVER (
            ORDER BY coalesce(ease_factor, 0) ASC, deck_created_at DESC
        ) + (_limit * 4) AS seq
    FROM base
    LIMIT _limit
),
dedup AS (
    SELECT DISTINCT ON (card_id)
        card_id,
        deck_id,
        deck_title,
        seq
    FROM pooled
    ORDER BY card_id, seq
)
SELECT
    c.id AS card_id,
    d.deck_id,
    d.deck_title,
    c.front,
    c.back
FROM dedup d
JOIN public.cards c ON c.id = d.card_id
ORDER BY
    CASE WHEN _mode = 'ordered' THEN d.seq ELSE NULL END ASC,
    CASE WHEN _mode = 'random' THEN random() ELSE NULL END
LIMIT COALESCE(_limit, 20);
$function$

-- 用户卡片视图：每张卡片的学习状态（带 deck 信息）
create or replace view public.user_card_stats_view as
with deck_cards as (
    select
        d.id as deck_id,
        d.title as deck_name,
        d.created_at as deck_created_at,
        (elem->>'card_id')::uuid as card_id
    from public.user_active_decks d
    cross join lateral jsonb_array_elements(d.items->'items') elem
)
select
  dc.card_id,
  dc.deck_id,
  dc.deck_name,
  dc.deck_created_at,
  c.created_at as card_created_at,
  cs.id is not null as learned,
  cs.last_reviewed_at as reviewed_at,
  cs.next_due_at,
  cs.ease_factor
from deck_cards dc
left join public.cards c on c.id = dc.card_id
left join public.card_stats cs
  on cs.card_id = dc.card_id
 and cs.user_id = auth.uid();

-- 用户 deck 统计视图（包含无卡片的 deck）
create or replace view public.user_deck_stats_view as
with deck_base as (
    select
        d.id as deck_id,
        d.title as deck_name,
        d.created_at as deck_created_at
    from public.user_active_decks d
), card_stats as (
    select
        deck_id,
        count(*) as item_count,
        sum(case when learned then 1 else 0 end) as learned_count,
        sum(case when (learned and next_due_at is null) or next_due_at <= now() then 1 else 0 end) as due_count,
        sum(coalesce(ease_factor, 0)) as ease_sum,
        sum(case when learned = false and card_created_at >= now() - interval '7 days' then 1 else 0 end) as recent_unlearned_count
    from public.user_card_stats_view
    group by deck_id
)
select
    b.deck_id,
    b.deck_name,
    b.deck_created_at,
    coalesce(s.item_count, 0) as item_count,
    coalesce(s.learned_count, 0) as learned_count,
    coalesce(s.due_count, 0) as due_count,
    coalesce(s.ease_sum, 0) as ease_sum,
    coalesce(s.recent_unlearned_count, 0) as recent_unlearned_count
from deck_base b
left join card_stats s on s.deck_id = b.deck_id;

-- 用户目录统计视图：基于 user_deck_stats_view 聚合
create or replace view public.user_folder_stats_view as
with deck_base as (
    select * from public.user_deck_stats_view
),
paths as (
    select
        b.deck_id,
        b.deck_name,
        b.item_count,
        b.learned_count,
        b.due_count,
        b.ease_sum,
        regexp_split_to_array(b.deck_name, '/'::text) as parts
    from deck_base b
),
prefixes as (
    select
        paths.deck_id,
        paths.item_count,
        paths.learned_count,
        paths.due_count,
        paths.ease_sum,
        array_to_string(paths.parts[1:s.i], '/'::text) as path
    from paths,
         lateral generate_subscripts(paths.parts, 1) s(i)
)
select
    path,
    (
        select id from decks d
        where d.title = p.path and d.owner_id = auth.uid()
        limit 1
    ) as deck_id,
    count(distinct deck_id) as deck_count,
    sum(item_count) as total_items,
    sum(learned_count) as total_learned,
    sum(due_count) as total_due,
    sum(ease_sum) as total_ease_factor,
    exists (
        select 1 from decks d
        where d.title = p.path and d.owner_id = auth.uid()
    ) as is_deck
from prefixes p
group by path
order by path;

-- 每日用户学习汇总（练习题/闪卡分开）
create table if not exists public.daily_user_stats (
    user_id uuid not null,
    date date not null,
    -- 练习题（测验）
    questions_reviewed int not null default 0,
    question_time_spent int not null default 0,       -- 秒
    quizzes jsonb,                                    -- 按测验分组的题目数量
    -- 闪卡
    cards_reviewed int not null default 0,
    card_time_spent int not null default 0,           -- 秒
    decks jsonb,                                      -- 按 deck 分组的卡片数量
    inserted_at timestamptz default now(),
    constraint daily_user_stats_pkey primary key (user_id, date)
);

-- 计算指定日期（可选用户）的统计，不落表，返回 daily_user_stats 结构
create or replace function public.compute_daily_user_stats(target_date date default current_date, target_user uuid default null)
returns table (
  user_id uuid,
  date date,
  questions_reviewed int,
  question_time_spent int,
  quizzes jsonb,
  cards_reviewed int,
  card_time_spent int,
  decks jsonb
)
language plpgsql
as $$
begin
  return query
  with base as (
    select
      cr.user_id,
      date(cr.reviewed_at) as day,
      cr.is_question,
      cr.belongs_to,
      count(*) as cnt,
      coalesce(sum(cr.time_spent), 0) as spent
    from card_reviews cr
    where date(cr.reviewed_at) = target_date
      and (target_user is null or cr.user_id = target_user)
    group by cr.user_id, day, cr.is_question, cr.belongs_to
  ),
  cards as (
    select
      base.user_id as user_id,
      base.day as day,
      sum(base.cnt)::int as cards_reviewed,
      sum(base.spent)::int as card_time_spent,
      jsonb_object_agg(d.title, base.cnt) filter (where d.title is not null) as decks
    from base
    left join decks d on d.id = base.belongs_to and d.is_deleted = false
    where base.is_question = false
    group by base.user_id, base.day
  ),
  quizzes as (
    select
      base.user_id as user_id,
      base.day as day,
      sum(base.cnt)::int as questions_reviewed,
      sum(base.spent)::int as question_time_spent,
      jsonb_object_agg(qt.title, base.cnt) filter (where qt.title is not null) as quizzes
    from base
    left join quizzes qt on qt.id = base.belongs_to and qt.is_deleted = false
    where base.is_question = true
    group by base.user_id, base.day
  )
  select
    coalesce(q.user_id, c.user_id) as user_id,
    coalesce(q.day, c.day) as date,
    coalesce(q.questions_reviewed, 0) as questions_reviewed,
    coalesce(q.question_time_spent, 0) as question_time_spent,
    q.quizzes,
    coalesce(c.cards_reviewed, 0) as cards_reviewed,
    coalesce(c.card_time_spent, 0) as card_time_spent,
    c.decks
  from quizzes q
  full join cards c
    on q.user_id = c.user_id and q.day = c.day;
end;
$$;

-- 批量补齐缺失的 daily_user_stats（默认补最近 30 天）
create or replace function public.compute_missing_daily_user_stats(p_days int default 30)
returns void
language plpgsql
as $$
declare
  target date;
begin
  if p_days is null or p_days < 1 then
    raise exception 'p_days must be >= 1';
  end if;

  -- 从昨天开始往前 p_days 天，缺失则补
  for target in select generate_series(current_date - 1, current_date - p_days, '-1 day'::interval)::date
  loop
    -- 若该日已存在记录，则跳过
    if exists (select 1 from daily_user_stats where date = target) then
      continue;
    end if;

    -- 计算该日所有用户的统计并写入 daily_user_stats
    insert into daily_user_stats (
      user_id, date,
      questions_reviewed, question_time_spent, quizzes,
      cards_reviewed, card_time_spent, decks
    )
    select
      user_id,
      date,
      questions_reviewed,
      question_time_spent,
      quizzes,
      cards_reviewed,
      card_time_spent,
      decks
    from public.compute_daily_user_stats(target, null)
    on conflict (user_id, date)
    do update set
      questions_reviewed = excluded.questions_reviewed,
      question_time_spent = excluded.question_time_spent,
      quizzes = excluded.quizzes,
      cards_reviewed = excluded.cards_reviewed,
      card_time_spent = excluded.card_time_spent,
      decks = excluded.decks,
      inserted_at = now();
  end loop;
end;
$$;
