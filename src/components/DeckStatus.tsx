import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { supabase } from "../../lib/supabaseClient";
import { Eye, Link } from "lucide-react";

interface DeckStatusProps {
    deckId: string;
    className?: string;
}

interface DeckInfo {
    totalItems: number;
    progress: number;
    recentUnlearned: number;
    dueCount: number;
    deckName: string;
}

export function DeckStatus({ deckId, className = "" }: DeckStatusProps) {
    const [info, setInfo] = useState<DeckInfo | null>(null);
    const [descriptionUrl, setDescriptionUrl] = useState<string | null>(null);
    const isEditMode =
        typeof window !== "undefined" &&
        localStorage.getItem("mode") === "edit";
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
            const { data, error } = await supabase
                .from("user_deck_stats_view")
                .select("deck_name, deck_description, item_count, ease_sum, recent_unlearned_count, due_count")
                .eq("deck_id", deckId)
                .maybeSingle();

            if (error || !data) {
                console.error("load deck status error", error);
                setInfo(null);
                setDescriptionUrl(null);
                return;
            }

            const totalItems = Number(data.item_count ?? 0);
            const easeSum = Number(data.ease_sum ?? 0);
            const progress = totalItems > 0
                ? Math.round((easeSum / (totalItems * 4)) * 100)
                : 0;
            const recent = Number(data.recent_unlearned_count ?? 0);
            const dueCount = Number(data.due_count ?? 0);

            setInfo({
                totalItems,
                progress,
                recentUnlearned: recent,
                dueCount,
                deckName: data.deck_name ?? "",
            });
            setDescriptionUrl(getHttpUrl(data.deck_description));
        }
        load();
    }, [deckId]);

    if (!deckId) return null;

    return (
        <section
            className={[
                "rounded-2xl bg-white px-3 py-2 dark:bg-slate-800",
                className,
            ].join(" ")}
        >
            <div className="flex items-center justify-between gap-2">
                {info ? (
                    <div className="text-xs text-slate-500 dark:text-slate-400 space-y-0.5">
                        <div>新卡片 {info.recentUnlearned}</div>
                        <div>待复习 {info.dueCount}</div>
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
                    {isEditMode && (
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
                    )}
                </div>
            </div>
        </section>
    );
}
