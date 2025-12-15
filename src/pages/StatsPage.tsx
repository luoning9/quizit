import { useCallback, useEffect, useMemo, useState } from "react";
import { supabase } from "../../lib/supabaseClient";
import { Button } from "../components/ui/Button";
import { useNavigate } from "react-router-dom";

type DailyStat = {
    user_id: string;
    date: string;
    questions_reviewed: number;
    question_time_spent: number;
    quizzes: Record<string, number> | null;
    cards_reviewed: number;
    card_time_spent: number;
    decks: Record<string, number> | null;
};

const CN_OFFSET_MINUTES = 8 * 60;

function formatDateCN(d: Date) {
    // 将时间调整到北京时间后取日期部分
    const shifted = new Date(d.getTime() + CN_OFFSET_MINUTES * 60 * 1000);
    return shifted.toISOString().slice(0, 10);
}

function getMonthRangeCN(monthStart: Date) {
    const year = monthStart.getUTCFullYear();
    const m = monthStart.getUTCMonth();
    const start = new Date(Date.UTC(year, m, 1));
    const end = new Date(Date.UTC(year, m + 1, 1));
    return { start, end };
}

function isSameDayCN(a: string, b: Date) {
    return a === formatDateCN(b);
}

export default function StatsPage() {
    const navigate = useNavigate();
    const today = useMemo(() => new Date(), []);
    const [userId, setUserId] = useState<string | null>(null);
    const [month, setMonth] = useState(() => {
        const now = new Date();
        return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
    });
    const [selectedDate, setSelectedDate] = useState<string>(() => formatDateCN(new Date()));
    const [monthStats, setMonthStats] = useState<Record<string, DailyStat>>({});
    const [monthLoading, setMonthLoading] = useState(false);
    const [monthError, setMonthError] = useState<string | null>(null);
    const [todayLive, setTodayLive] = useState<DailyStat | null>(null);
    const [liveLoading, setLiveLoading] = useState(false);
    const [liveError, setLiveError] = useState<string | null>(null);
    const [authChecked, setAuthChecked] = useState(false);
    const [deckNames, setDeckNames] = useState<Record<string, { name: string; deleted: boolean }>>({});
    const [quizNames, setQuizNames] = useState<Record<string, { name: string; deleted: boolean }>>({});

    // 获取用户 ID
    useEffect(() => {
        supabase.auth.getUser().then(({ data, error }) => {
            if (error) {
                console.error("load user error", error);
            } else {
                setUserId(data.user?.id ?? null);
            }
            setAuthChecked(true);
        });
    }, []);

    // 读取当月统计
    useEffect(() => {
        if (!userId) return;
        const { start, end } = getMonthRangeCN(month);
        setMonthLoading(true);
        setMonthError(null);

        supabase
            .from("daily_user_stats")
            .select("user_id, date, questions_reviewed, question_time_spent, quizzes, cards_reviewed, card_time_spent, decks")
            .eq("user_id", userId)
            .gte("date", formatDateCN(start))
            .lt("date", formatDateCN(end))
            .then(({ data, error }) => {
                if (error) {
                    console.error("load month stats error", error);
                    setMonthError("加载统计失败");
                    setMonthLoading(false);
                    return;
                }
                const map: Record<string, DailyStat> = {};
                (data || []).forEach((row) => {
                    map[(row as DailyStat).date] = row as DailyStat;
                });
                setMonthStats(map);
                // 当前月且缺失昨天记录时尝试补数据
                const isCurrentMonth =
                    month.getUTCFullYear() === today.getUTCFullYear() &&
                    month.getUTCMonth() === today.getUTCMonth();
                if (isCurrentMonth) {
                    const yesterday = new Date();
                    yesterday.setUTCDate(yesterday.getUTCDate() - 1);
                    const yesterdayStr = formatDateCN(yesterday);
                    const hasYesterday = Boolean(map[yesterdayStr]);
                    if (!hasYesterday) {
                        supabase
                            .rpc("compute_missing_daily_user_stats", { p_days: 1 })
                            .then(({ error: missErr }) => {
                                if (missErr) {
                                    console.error("补齐昨天统计失败", missErr);
                                } else {
                                    // 重新加载当月数据
                                    setMonth((prev) => new Date(prev)); // trigger effect
                                }
                            });
                    }
                }
                setMonthLoading(false);
            });
    }, [userId, month]);

    const mergedStats = useMemo(() => {
        const merged = { ...monthStats };
        if (todayLive) {
            merged[todayLive.date] = todayLive;
        }
        return merged;
    }, [monthStats, todayLive]);

    const todayStr = useMemo(() => formatDateCN(today), [today]);
    const isFutureSelected = selectedDate > todayStr;
    const selectedStat = isFutureSelected ? null : mergedStats[selectedDate] ?? null;

    const fetchNames = useCallback(
        async (ids: string[], type: "deck" | "quiz") => {
            const unique = Array.from(new Set(ids)).filter(Boolean);
            if (!unique.length) return;
            const cache = type === "deck" ? deckNames : quizNames;
            const missing = unique.filter((id) => !cache[id]);
            if (!missing.length) return;
            const { data, error } = await supabase
                .from(type === "deck" ? "decks" : "quizzes")
                .select("id, title, is_deleted")
                .in("id", missing);
            if (error) {
                console.error(`load ${type} names error`, error);
                return;
            }
            const map: Record<string, { name: string; deleted: boolean }> = {};
            (data || []).forEach((row: any) => {
                if (row?.id) map[row.id] = { name: row.title ?? row.id, deleted: !!row.is_deleted };
            });
            if (type === "deck") {
                setDeckNames((prev) => ({ ...prev, ...map }));
            } else {
                setQuizNames((prev) => ({ ...prev, ...map }));
            }
        },
        [deckNames, quizNames]
    );

    // 今天实时数据
    const loadLiveToday = useCallback(() => {
        if (!userId) return;
        const selectedIsToday = isSameDayCN(selectedDate, today);
        if (!selectedIsToday) return;
        setLiveLoading(true);
        setLiveError(null);
        supabase
            .rpc("compute_daily_user_stats", { target_date: selectedDate, target_user: userId })
            .then(({ data, error }) => {
                if (error) {
                    console.error("compute today stats error", error);
                    setLiveError("实时统计失败");
                    setLiveLoading(false);
                    return;
                }
                const found = Array.isArray(data) ? (data as DailyStat[]).find((d) => d.date === selectedDate) : null;
                setTodayLive(found ?? null);
                setLiveLoading(false);
            });
    }, [selectedDate, today, userId]);

    useEffect(() => {
        void loadLiveToday();
    }, [loadLiveToday]);

    const daysInMonth = useMemo(() => {
        const year = month.getUTCFullYear();
        const m = month.getUTCMonth();
        return new Date(Date.UTC(year, m + 1, 0)).getUTCDate();
    }, [month]);

    const startWeekday = useMemo(() => {
        const copy = new Date(month);
        return copy.getUTCDay(); // 0-6
    }, [month]);

    useEffect(() => {
        const decksObj = selectedStat?.decks ?? null;
        const deckIds = decksObj ? Object.keys(decksObj) : [];
        void fetchNames(deckIds, "deck");
        const quizzesObj = selectedStat?.quizzes ?? null;
        const quizIds = quizzesObj ? Object.keys(quizzesObj) : [];
        void fetchNames(quizIds, "quiz");
    }, [selectedStat, fetchNames]);

    function changeMonth(offset: number) {
        setMonth((prev) => {
            const next = new Date(Date.UTC(prev.getUTCFullYear(), prev.getUTCMonth() + offset, 1));
            const thisMonthStart = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 1));
            if (next > thisMonthStart) {
                return prev; // 不允许选择未来的月份
            }
            // 切换月份后，选中该月第一天（若是本月且未来则回退到今天）
            const nextSelected = new Date(Date.UTC(next.getUTCFullYear(), next.getUTCMonth(), 1));
            const nextMonthStartStr = formatDateCN(nextSelected);
            const todayStr = formatDateCN(today);
            setSelectedDate(nextSelected > today ? todayStr : nextMonthStartStr);
            return next;
        });
    }

    function handleSelectDate(dateStr: string) {
        if (dateStr > todayStr) return;
        const stat = mergedStats[dateStr];
        if (!stat || ((stat.cards_reviewed ?? 0) === 0 && (stat.questions_reviewed ?? 0) === 0)) {
            return;
        }
        setSelectedDate(dateStr);
    }

    function renderDayCell(day: number) {
        const dateStr = formatDateCN(new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth(), day)));
        const stat = mergedStats[dateStr];
        const isToday = isSameDayCN(dateStr, today);
        const isSelected = selectedDate === dateStr;
        const isFuture = dateStr > todayStr;
        const cardCount = stat?.cards_reviewed ?? 0;
        const quizCount = stat?.questions_reviewed ?? 0;
        const isEmptyDay = cardCount === 0 && quizCount === 0;
        const disabled = isFuture || isEmptyDay;
        return (
            <button
                key={dateStr}
                onClick={() => handleSelectDate(dateStr)}
                disabled={disabled}
                className={`h-16 w-full rounded-xl border transition flex flex-col items-start justify-between p-2 text-left ${
                    isSelected
                        ? "border-emerald-500 bg-emerald-50 dark:border-emerald-400 dark:bg-emerald-500/10"
                        : "border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"
                } ${isToday ? "bg-gradient-to-br from-blue-100/80 to-blue-50/70 dark:from-blue-950/50 dark:to-blue-900/40 border-blue-400 dark:border-blue-500 shadow-inner" : ""} ${disabled && !isToday ? "opacity-40 cursor-not-allowed" : ""}`}
            >
                <div className="flex items-start justify-between w-full gap-2">
                    <div className="text-2xl font-semibold tracking-tight leading-none text-slate-400 dark:text-slate-500">{day}</div>
                    <div className="flex-1 flex flex-col items-end text-xs text-slate-600 dark:text-slate-300 pr-1">
                        {!isEmptyDay ? (
                            <>
                                <span className="inline-flex min-w-[2rem] justify-center rounded-full px-1.5 py-0.5 bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-100 font-semibold font-mono text-sm">
                                    {cardCount}
                                </span>
                                <span className="inline-flex min-w-[2rem] justify-center rounded-full px-1.5 py-0.5 bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-100 font-semibold font-mono text-sm">
                                    {quizCount}
                                </span>
                            </>
                        ) : (
                            <span className="text-[11px] text-slate-400 dark:text-slate-500">无数据</span>
                        )}
                    </div>
                </div>
            </button>
        );
    }

    const calendarCells = useMemo(() => {
        const blanks = Array.from({ length: startWeekday }, (_, idx) => <div key={`blank-${idx}`} />);
        const days = Array.from({ length: daysInMonth }, (_, idx) => renderDayCell(idx + 1));
        return [...blanks, ...days];
    }, [startWeekday, daysInMonth, mergedStats, selectedDate]);

    function renderDetailRow(label: string, value: number | null, unit = "") {
        return (
            <div className="flex items-center justify-between text-sm text-slate-700 dark:text-slate-200">
                <span className="text-slate-500 dark:text-slate-400">{label}</span>
                <span className="font-semibold">{value ?? 0}{unit}</span>
            </div>
        );
    }

function renderMap(
    obj: Record<string, unknown> | null,
    emptyText: string,
    type: "deck" | "quiz",
    onNavigate?: (path: string) => void,
    nameMap?: Record<string, { name: string; deleted: boolean }>
) {
    const entries = obj ? Object.entries(obj) : [];
    if (!entries.length) return <div className="text-xs text-slate-500 dark:text-slate-400">{emptyText}</div>;
    return (
        <div className="space-y-2">
            {entries.map(([key, payload]) => {
                const isNumber = typeof payload === "number";
                const cnt = isNumber ? (payload as number) : (payload as any)?.count ?? 0;
                const id = isNumber ? key : (payload as any)?.id ?? key;
                const nameEntry = nameMap?.[id] ?? null;
                const nameFallback = nameEntry?.name ?? key;
                const name = isNumber ? nameFallback : (payload as any)?.name ?? nameFallback;
                const deleted = nameEntry?.deleted ?? false;
                const href =
                    id && type === "deck"
                        ? `/decks/${encodeURIComponent(id)}/edit`
                        : id && type === "quiz"
                            ? `/quiz-runs/${encodeURIComponent(id)}`
                            : undefined;
                const clickable = href && onNavigate && !deleted;
                const Wrapper: any = clickable ? "button" : "div";
                return (
                    <Wrapper
                        key={name}
                        onClick={clickable ? () => onNavigate?.(href!) : undefined}
                        className={`flex items-center justify-between text-sm text-slate-700 dark:text-slate-200 hover:text-emerald-600 dark:hover:text-emerald-300 ${clickable ? "w-full text-left cursor-pointer" : ""}`}
                        type={clickable ? "button" : undefined}
                    >
                        <span
                            className="max-w-[65%] inline-block overflow-hidden text-ellipsis whitespace-nowrap text-left"
                            style={{ direction: "rtl" }}
                            title={name}
                        >
                            {name}
                        </span>
                        <span className="font-semibold">{cnt}</span>
                    </Wrapper>
                );
            })}
        </div>
    );
}

    const monthLabel = `${month.getUTCFullYear()}-${String(month.getUTCMonth() + 1).padStart(2, "0")}`;

    if (!authChecked) {
        return <div className="text-sm text-slate-600 dark:text-slate-300">正在加载用户信息…</div>;
    }

    if (!userId) {
        return <div className="text-sm text-amber-600 dark:text-amber-300">请先登录以查看学习统计。</div>;
    }

    return (
        <div className="space-y-6">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                    <div className="text-sm text-slate-500 dark:text-slate-400">学习统计</div>
                    <div className="text-xl font-semibold text-slate-900 dark:text-slate-50">月度视图</div>
                </div>
                <div className="flex items-center gap-3">
                    <Button variant="ghost" onClick={() => changeMonth(-1)} disabled={monthLoading}>上个月</Button>
                    <span className="text-base font-medium text-slate-800 dark:text-slate-200">{monthLabel}</span>
                    <Button variant="ghost" onClick={() => changeMonth(1)} disabled={monthLoading}>下个月</Button>
                </div>
            </div>

            {monthError && (
                <div className="text-sm text-rose-600 dark:text-rose-400">{monthError}</div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="lg:col-span-2 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-900">
                    <div className="grid grid-cols-7 gap-2 text-xl text-slate-500 dark:text-slate-400 mb-2">
                        {["日", "一", "二", "三", "四", "五", "六"].map((d) => (
                            <div key={d} className="text-center font-medium">{d}</div>
                        ))}
                    </div>
                    {monthLoading ? (
                        <div className="text-sm text-slate-500 dark:text-slate-300">加载中…</div>
                    ) : (
                        <div className="grid grid-cols-7 gap-2">
                            {calendarCells}
                        </div>
                    )}
                </div>

                <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900 text-base">
                    <div className="flex items-center justify-between mb-3">
                        <div>
                            <div className="text-sm text-slate-500 dark:text-slate-400">日期</div>
                            <div className="text-xl font-semibold text-slate-900 dark:text-slate-100">{selectedDate}</div>
                        </div>
                        {isSameDayCN(selectedDate, today) && (
                            <Button
                                variant="outline"
                                className="px-3 py-1 text-base"
                                onClick={loadLiveToday}
                                disabled={liveLoading}
                            >
                                {liveLoading ? "刷新中…" : "刷新"}
                            </Button>
                        )}
                    </div>

                    {liveError && (
                        <div className="text-xs text-amber-600 dark:text-amber-400 mb-2">{liveError}</div>
                    )}

                    {selectedStat ? (
                        selectedStat.cards_reviewed === 0 && selectedStat.questions_reviewed === 0 ? (
                            <div className="text-sm text-slate-500 dark:text-slate-400">当日暂无数据。</div>
                        ) : (
                            <div className="space-y-4">
                                {selectedStat.cards_reviewed > 0 && (
                                    <div className="rounded-xl bg-blue-50 px-3 py-2 dark:bg-blue-900/30">
                                        <div className="text-xs text-blue-700 dark:text-blue-200 mb-1">闪卡</div>
                                        {renderDetailRow("卡片数", selectedStat.cards_reviewed)}
                                        {renderDetailRow("用时", selectedStat.card_time_spent, "s")}
                                        <div className="mt-2">{renderMap(selectedStat.decks, "当日没有闪卡数据", "deck", navigate, deckNames)}</div>
                                    </div>
                                )}

                                {selectedStat.questions_reviewed > 0 && (
                                    <div className="rounded-xl bg-amber-50 px-3 py-2 dark:bg-amber-900/30">
                                        <div className="text-xs text-amber-700 dark:text-amber-200 mb-1">测验</div>
                                        {renderDetailRow("题目数", selectedStat.questions_reviewed)}
                                        {renderDetailRow("用时", selectedStat.question_time_spent, "s")}
                                        <div className="mt-2">{renderMap(selectedStat.quizzes, "当日没有测验数据", "quiz", navigate, quizNames)}</div>
                                    </div>
                                )}
                            </div>
                        )
                    ) : (
                        <div className="text-sm text-slate-500 dark:text-slate-400">当日暂无数据。</div>
                    )}
                </div>
            </div>
        </div>
    );
}
