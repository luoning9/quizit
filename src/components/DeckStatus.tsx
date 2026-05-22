import { useNavigate } from "react-router-dom";
import { Eye, Link } from "lucide-react";

interface DeckStatusProps {
    deckId: string;
    isOwned?: boolean;
    totalItems?: number;
    progress?: number;
    recentUnlearned?: number;
    dueCount?: number;
    deckDescription?: string | null;
    className?: string;
}

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

export function DeckStatus({
    deckId,
    isOwned = false,
    totalItems = 0,
    progress = 0,
    recentUnlearned = 0,
    dueCount = 0,
    deckDescription = null,
    className = "",
}: DeckStatusProps) {
    const isEditMode =
        typeof window !== "undefined" &&
        localStorage.getItem("mode") === "edit";
    const navigate = useNavigate();
    const descriptionUrl = getHttpUrl(deckDescription);

    const openDeckApp = () => {
        if (!descriptionUrl) return;
        const newWindow = window.open(descriptionUrl, "deck-app");
        if (newWindow) {
            newWindow.opener = null;
        }
    };

    if (!deckId) return null;

    return (
        <section
            className={[
                "rounded-2xl bg-white px-3 py-2 dark:bg-slate-800",
                className,
            ].join(" ")}
        >
            <div className="flex items-center justify-between gap-2">
                <div className="text-xs text-slate-500 dark:text-slate-400 space-y-0.5">
                    <div>新卡片 {recentUnlearned}</div>
                    <div>待复习 {dueCount}</div>
                    <div className="text-[10px] text-slate-400 dark:text-slate-500">
                        {totalItems} cards · {progress}%
                    </div>
                </div>
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
                    {isEditMode && isOwned && (
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
