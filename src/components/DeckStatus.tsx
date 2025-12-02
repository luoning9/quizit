import React, { useEffect, useState } from "react";
import { supabase } from "../../lib/supabaseClient";

interface DeckStatusProps {
    deckId: string;
}

interface DeckInfo {
    totalItems: number;
    progress: number;
}

export function DeckStatus({ deckId }: DeckStatusProps) {
    const [info, setInfo] = useState<DeckInfo | null>(null);

    useEffect(() => {
        async function load() {
            if (!deckId) return;
            const { data, error } = await supabase
                .from("deck_folder_stats")
                .select("total_items, total_ease_factor")
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
            setInfo({ totalItems, progress });
        }
        load();
    }, [deckId]);

    if (!deckId) return null;

    return (
        <section className="rounded-2xl border border-slate-200 bg-white/80 p-4 shadow-sm dark:border-slate-700/70 dark:bg-slate-900/60">
            {info ? (
                <div className="text-xs text-slate-500 dark:text-slate-400">
                    {info.totalItems} 张卡片 · 进度 {info.progress}%
                </div>
            ) : (
                <div className="text-sm text-slate-500 dark:text-slate-400">加载中…</div>
            )}
        </section>
    );
}

