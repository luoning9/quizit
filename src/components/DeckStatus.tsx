import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { supabase } from "../../lib/supabaseClient";
import { Pencil } from "lucide-react";

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
    const navigate = useNavigate();

    useEffect(() => {
        async function load() {
            if (!deckId) return;
            const { data, error } = await supabase
                .from("user_deck_stats_view")
                .select("item_count, ease_sum, recent_unlearned_count")
                .eq("deck_id", deckId)
                .maybeSingle();

            if (error || !data) {
                console.error("load deck status error", error);
                setInfo(null);
                return;
            }

            const totalItems = Number(data.item_count ?? 0);
            const easeSum = Number(data.ease_sum ?? 0);
            const progress = totalItems > 0
                ? Math.round((easeSum / (totalItems * 4)) * 100)
                : 0;
            const recent = Number(data.recent_unlearned_count ?? 0);

            setInfo({ totalItems, progress, recentUnlearned: recent });
        }
        load();
    }, [deckId]);

    if (!deckId) return null;

    return (
        <section className="rounded-2xl border border-slate-200 bg-white/80 p-4 shadow-sm dark:border-slate-700/70 dark:bg-slate-900/60">
            <div className="flex items-center justify-between gap-2">
                {info ? (
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                        {info.totalItems} 张卡片 · 进度 {info.progress}% · 最近新增未学 {info.recentUnlearned}
                    </div>
                ) : (
                    <div className="text-sm text-slate-500 dark:text-slate-400">加载中…</div>
                )}
                <button
                    type="button"
                    className="p-2 rounded-full text-emerald-600 hover:text-white hover:bg-emerald-600 dark:text-emerald-300 dark:hover:text-emerald-50 dark:hover:bg-emerald-700"
                    title="编辑"
                    onClick={() => {
                        navigate(`/decks/${deckId}/edit`);
                    }}
                >
                    <Pencil className="w-5 h-5" />
                </button>
            </div>
        </section>
    );
}
