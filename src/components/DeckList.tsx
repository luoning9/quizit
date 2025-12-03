import React from "react";

export type DeckListItem = {
  deck_id: string;
  deck_name: string;
  deck_created_at: string | null;
  item_count: number;
  learned_count: number | null;
  due_count: number | null;
  recent_unlearned_count?: number | null;
};

interface DeckListProps {
  decks: DeckListItem[];
  onLearn: (deck: DeckListItem) => void;
  onView: (deck: DeckListItem) => void;
  emptyText?: string;
}

function formatDate(dt: string | null) {
  if (!dt) return "-";
  const d = new Date(dt);
  if (Number.isNaN(d.getTime())) return dt;
  return d.toLocaleString();
}

export function DeckList({
  decks,
  onLearn,
  onView,
  emptyText = "暂无数据",
}: DeckListProps) {
  if (!decks.length) {
    return <div className="text-base text-slate-500 dark:text-slate-400">{emptyText}</div>;
  }

  return (
    <div className="space-y-3">
      {decks.map((deck) => {
        const recentBadge = deck.recent_unlearned_count ?? 0;
        const dueBadge = deck.due_count ?? 0;
        return (
          <div
            key={deck.deck_id}
            className="flex items-center justify-between rounded-xl border border-slate-200 bg-white/80 px-4 py-3 shadow-sm dark:border-slate-700 dark:bg-slate-900/60"
          >
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <div className="text-base font-semibold">{deck.deck_name}</div>
                {recentBadge > 0 && (
                  <div className="h-6 min-w-6 px-2 rounded-full text-xs flex items-center justify-center bg-amber-400 text-slate-900 font-semibold">
                    {recentBadge >= 100 ? "99+" : recentBadge}
                  </div>
                )}
                {dueBadge > 0 && (
                  <div className="h-6 min-w-6 px-2 rounded-full text-xs flex items-center justify-center bg-red-500 text-white">
                    {dueBadge >= 100 ? "99+" : dueBadge}
                  </div>
                )}
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                创建：{formatDate(deck.deck_created_at)} · 共 {deck.item_count ?? 0} 张 · 已学 {deck.learned_count ?? 0} · 待复习 {deck.due_count ?? 0}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                className="px-3 py-1.5 rounded-lg bg-emerald-500 text-white text-sm hover:bg-emerald-600"
                onClick={() => onLearn(deck)}
              >
                学习
              </button>
              <button
                className="px-3 py-1.5 rounded-lg border border-slate-300 text-sm text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
                onClick={() => onView(deck)}
              >
                查看
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
