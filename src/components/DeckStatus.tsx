import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { supabase } from "../../lib/supabaseClient";
import { Eye, Link } from "lucide-react";

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
    const [descriptionUrl, setDescriptionUrl] = useState<string | null>(null);
    const navigate = useNavigate();

    const openDeckApp = () => {
        if (!descriptionUrl) return;
        const newWindow = window.open(descriptionUrl, "deck-app");
        if (newWindow) {
            newWindow.opener = null;
        }
    };

    const getHttpUrl = (raw: string | null | undefined): string | null => {
        const trimmed = raw?.trim();
        if (!trimmed) return null;
        try {
            const url = new URL(trimmed);
            if (url.protocol === "http:" || url.protocol === "https:") {
                return url.toString();
            }
        } catch {
            // ignore invalid URLs
        }
        return null;
    };

    useEffect(() => {
        async function load() {
            if (!deckId) return;
            const [statsResult, deckResult] = await Promise.all([
                supabase
                    .from("user_deck_stats_view")
                    .select("item_count, ease_sum, recent_unlearned_count")
                    .eq("deck_id", deckId)
                    .maybeSingle(),
                supabase
                    .from("decks")
                    .select("description")
                    .eq("id", deckId)
                    .maybeSingle(),
            ]);

            if (statsResult.error || !statsResult.data) {
                console.error("load deck status error", statsResult.error);
                setInfo(null);
            } else {
                const totalItems = Number(statsResult.data.item_count ?? 0);
                const easeSum = Number(statsResult.data.ease_sum ?? 0);
                const progress = totalItems > 0
                    ? Math.round((easeSum / (totalItems * 4)) * 100)
                    : 0;
                const recent = Number(statsResult.data.recent_unlearned_count ?? 0);

                setInfo({ totalItems, progress, recentUnlearned: recent });
            }

            if (deckResult.error) {
                console.error("load deck description error", deckResult.error);
                setDescriptionUrl(null);
            } else {
                setDescriptionUrl(getHttpUrl(deckResult.data?.description));
            }
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
                <div className="flex items-center gap-2">
                    {descriptionUrl && (
                        <button
                            type="button"
                            className="p-2 rounded-full text-emerald-600 hover:text-white hover:bg-emerald-600 dark:text-emerald-300 dark:hover:text-emerald-50 dark:hover:bg-emerald-700"
                            title="访问相关app"
                            onClick={openDeckApp}
                        >
                            <Link className="w-4 h-4" />
                        </button>
                    )}
                    <button
                        type="button"
                        className="p-2 rounded-full text-emerald-600 hover:text-white hover:bg-emerald-600 dark:text-emerald-300 dark:hover:text-emerald-50 dark:hover:bg-emerald-700"
                        title="查看"
                        onClick={() => {
                            navigate(`/decks/${deckId}/edit`);
                        }}
                    >
                        <Eye className="w-5 h-5" />
                    </button>
                </div>
            </div>
        </section>
    );
}
