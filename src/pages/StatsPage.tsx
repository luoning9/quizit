import { useCallback, useEffect, useMemo, useState } from "react";
import { supabase } from "../../lib/supabaseClient";
import { Button } from "../components/ui/Button";

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

function formatDate(d: Date) {
    return d.toISOString().slice(0, 10);
}

function getMonthRange(month: Date) {
    const year = month.getFullYear();
    const m = month.getMonth();
    const start = new Date(Date.UTC(year, m, 1));
    const end = new Date(Date.UTC(year, m + 1, 1));
    return { start, end };
}

function isSameDay(a: string, b: Date) {
    return a === formatDate(b);
}

export default function StatsPage() {
    const today = useMemo(() => new Date(), []);
    const [userId, setUserId] = useState<string | null>(null);
    const [month, setMonth] = useState(() => {
        const now = new Date();
        return new Date(Date.UTC(now.getFullYear(), now.getMonth(), 1));
    });
    const [selectedDate, setSelectedDate] = useState<string>(() => formatDate(new Date()));
    const [monthStats, setMonthStats] = useState<Record<string, DailyStat>>({});
    const [monthLoading, setMonthLoading] = useState(false);
    const [monthError, setMonthError] = useState<string | null>(null);
    const [todayLive, setTodayLive] = useState<DailyStat | null>(null);
    const [liveLoading, setLiveLoading] = useState(false);
    const [liveError, setLiveError] = useState<string | null>(null);
    const [authChecked, setAuthChecked] = useState(false);

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
        const { start, end } = getMonthRange(month);
        setMonthLoading(true);
        setMonthError(null);

        supabase
            .from("daily_user_stats")
            .select("user_id, date, questions_reviewed, question_time_spent, quizzes, cards_reviewed, card_time_spent, decks")
            .eq("user_id", userId)
            .gte("date", formatDate(start))
            .lt("date", formatDate(end))
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
                setMonthLoading(false);
            });
    }, [userId, month]);

    // 今天实时数据
    const loadLiveToday = useCallback(() => {
        if (!userId) return;
        const selectedIsToday = isSameDay(selectedDate, today);
        if (!selectedIsToday) {
            setTodayLive(null);
            return;
        }
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

    const mergedStats = useMemo(() => {
        const merged = { ...monthStats };
        if (todayLive) {
            merged[todayLive.date] = todayLive;
        }
        return merged;
    }, [monthStats, todayLive]);

    const selectedStat = mergedStats[selectedDate] ?? null;

    function changeMonth(offset: number) {
        setMonth((prev) => new Date(Date.UTC(prev.getUTCFullYear(), prev.getUTCMonth() + offset, 1)));
    }

    function handleSelectDate(dateStr: string) {
        setSelectedDate(dateStr);
    }

    function renderDayCell(day: number) {
        const dateStr = formatDate(new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth(), day)));
        const stat = mergedStats[dateStr];
        const isToday = isSameDay(dateStr, today);
        const isSelected = selectedDate === dateStr;
        const cardCount = stat?.cards_reviewed ?? 0;
        const quizCount = stat?.questions_reviewed ?? 0;
        return (
            <button
                key={dateStr}
                onClick={() => handleSelectDate(dateStr)}
                className={`h-20 w-full rounded-xl border transition flex flex-col items-start justify-between p-2 text-left ${
                    isSelected
                        ? "border-emerald-500 bg-emerald-50 dark:border-emerald-400 dark:bg-emerald-500/10"
                        : "border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"
                } ${isToday ? "ring-2 ring-blue-400" : ""}`}
            >
                <div className="flex items-center justify-between w-full text-xs text-slate-600 dark:text-slate-300">
                    <span className="font-semibold text-slate-800 dark:text-slate-100">{day}</span>
                    {isToday && <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200">今天</span>}
                </div>
                <div className="w-full space-y-1 text-[11px] text-slate-500 dark:text-slate-300">
                    <div className="flex items-center justify-between">
                        <span className="rounded px-2 py-0.5 bg-blue-50 text-blue-700 dark:bg-blue-900/40 dark:text-blue-200">闪卡</span>
                        <span className="font-semibold text-blue-700 dark:text-blue-200">{cardCount}</span>
                    </div>
                    <div className="flex items-center justify-between">
                        <span className="rounded px-2 py-0.5 bg-amber-50 text-amber-700 dark:bg-amber-900/40 dark:text-amber-200">测验</span>
                        <span className="font-semibold text-amber-700 dark:text-amber-200">{quizCount}</span>
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

    function renderMap(obj: Record<string, number> | null, emptyText: string) {
        const entries = obj ? Object.entries(obj) : [];
        if (!entries.length) return <div className="text-xs text-slate-500 dark:text-slate-400">{emptyText}</div>;
        return (
            <div className="space-y-2">
                {entries.map(([name, cnt]) => (
                    <div key={name} className="flex items-center justify-between text-sm text-slate-700 dark:text-slate-200">
                        <span className="truncate max-w-[65%]" title={name}>{name}</span>
                        <span className="font-semibold">{cnt}</span>
                    </div>
                ))}
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
                    <div className="grid grid-cols-7 gap-2 text-xs text-slate-500 dark:text-slate-400 mb-2">
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

                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-900">
                    <div className="flex items-center justify-between mb-3">
                        <div>
                            <div className="text-xs text-slate-500 dark:text-slate-400">日期</div>
                            <div className="text-lg font-semibold text-slate-900 dark:text-slate-100">{selectedDate}</div>
                        </div>
                        {isSameDay(selectedDate, today) && (
                            <Button
                                variant="outline"
                                className="px-3 py-1 text-sm"
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
                        <div className="space-y-4">
                            <div className="rounded-xl bg-blue-50 px-3 py-2 dark:bg-blue-900/30">
                                <div className="text-xs text-blue-700 dark:text-blue-200 mb-1">闪卡</div>
                                {renderDetailRow("卡片数", selectedStat.cards_reviewed)}
                                {renderDetailRow("用时", selectedStat.card_time_spent, "s")}
                                <div className="mt-2">{renderMap(selectedStat.decks, "当日没有闪卡数据")}</div>
                            </div>

                            <div className="rounded-xl bg-amber-50 px-3 py-2 dark:bg-amber-900/30">
                                <div className="text-xs text-amber-700 dark:text-amber-200 mb-1">测验</div>
                                {renderDetailRow("题目数", selectedStat.questions_reviewed)}
                                {renderDetailRow("用时", selectedStat.question_time_spent, "s")}
                                <div className="mt-2">{renderMap(selectedStat.quizzes, "当日没有测验数据")}</div>
                            </div>
                        </div>
                    ) : (
                        <div className="text-sm text-slate-500 dark:text-slate-400">当日暂无数据。</div>
                    )}
                </div>
            </div>
        </div>
    );
}
