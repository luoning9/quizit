import { useEffect, useState } from "react";
import { supabase } from "../../lib/supabaseClient";

interface DeckStatusProps {
    deckId: string;
}

interface DeckInfo {
    totalItems: number;
    progress: number;
    recentUnlearned: number;
}

export function DeckStatus({ deckId }: DeckStatusProps) {
    const [info, setInfo] = useState<DeckInfo | null>(null);

    useEffect(() => {
        async function load() {
            if (!deckId) return;
            const { data, error } = await supabase
                .from("deck_folder_stats")
                .select("total_items, total_ease_factor, deck_id")
                .eq("deck_id", deckId)
                .maybeSingle();
            if (error || !data) {
                console.error("load deck status error", error);
                setInfo(null);
                return;
            }
            const totalItems = data.total_items ?? 0;
            const progress = totalItems > 0
                ? Math.round((Number(data.total_ease_factor ?? 0) / (totalItems * 4)) * 100)
                : 0;
            // recent_unlearned_count 在 deck 视图里没有，转而查 user_deck_stats_view
            const { data: stats, error: statsErr } = await supabase
                .from("user_deck_stats_view")
                .select("recent_unlearned_count")
                .eq("deck_id", deckId)
                .maybeSingle();
            const recent = stats && !statsErr ? Number(stats.recent_unlearned_count ?? 0) : 0;

            setInfo({ totalItems, progress, recentUnlearned: recent });
        }
        load();
    }, [deckId]);

    if (!deckId) return null;

    return (
        <section className="rounded-2xl border border-slate-200 bg-white/80 p-4 shadow-sm dark:border-slate-700/70 dark:bg-slate-900/60">
            {info ? (
                <div className="text-xs text-slate-500 dark:text-slate-400">
                    {info.totalItems} 张卡片 · 进度 {info.progress}% · 最近新增未学 {info.recentUnlearned}
                </div>
            ) : (
                <div className="text-sm text-slate-500 dark:text-slate-400">加载中…</div>
            )}
        </section>
    );
}
