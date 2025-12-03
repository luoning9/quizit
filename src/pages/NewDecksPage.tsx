import React, { useEffect, useState } from "react";
import { supabase } from "../../lib/supabaseClient";
import { Button } from "../components/ui/Button";
import { useNavigate } from "react-router-dom";

type DeckRow = {
  deck_id: string;
  deck_name: string;
  deck_created_at: string | null;
  item_count: number;
  learned_count: number | null;
  due_count: number | null;
};

function formatDate(dt: string | null) {
  if (!dt) return "-";
  const d = new Date(dt);
  if (Number.isNaN(d.getTime())) return dt;
  return d.toLocaleString();
}

export default function NewDecksPage() {
  const [decks, setDecks] = useState<DeckRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      const { data, error } = await supabase
        .from("user_deck_stats_view")
        .select(
          "deck_id, deck_name, deck_created_at, item_count, learned_count, due_count"
        )
        .order("deck_created_at", { ascending: false });

      if (error) {
        console.error("load new decks error", error);
        setError("加载列表失败");
      } else {
        setDecks((data as DeckRow[]) ?? []);
      }
      setLoading(false);
    }
    void load();
  }, []);

  return (
    <div className="max-w-4xl mx-auto py-8 px-4 space-y-6 text-slate-900 dark:text-slate-100">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">新增 Deck 列表</h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            按创建时间倒序，方便快速开始学习
          </p>
        </div>
        <Button variant="outline" onClick={() => navigate("/decks")}>
          返回目录
        </Button>
      </div>

      {loading && (
        <div className="text-sm text-slate-500 dark:text-slate-400">
          正在加载…
        </div>
      )}
      {error && (
        <div className="text-sm text-red-500 dark:text-red-400">{error}</div>
      )}

      {!loading && !error && (
        <div className="space-y-3">
          {decks.length === 0 ? (
            <div className="text-sm text-slate-500 dark:text-slate-400">
              暂无数据
            </div>
          ) : (
            decks.map((deck) => (
              <div
                key={deck.deck_id}
                className="flex items-center justify-between rounded-xl border border-slate-200 bg-white/80 px-4 py-3 shadow-sm dark:border-slate-700 dark:bg-slate-900/60"
              >
                <div className="flex flex-col gap-1">
                  <div className="text-sm font-semibold">{deck.deck_name}</div>
                  <div className="text-[11px] text-slate-500 dark:text-slate-400">
                    创建：{formatDate(deck.deck_created_at)} · 共{" "}
                    {deck.item_count ?? 0} 张 · 已学{" "}
                    {deck.learned_count ?? 0} · 待复习{" "}
                    {deck.due_count ?? 0}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="primary"
                    className="text-sm"
                    onClick={() =>
                      navigate(
                        `/decks/${encodeURIComponent(deck.deck_name)}/practice`
                      )
                    }
                  >
                    学习
                  </Button>
                  <Button
                    variant="outline"
                    className="text-sm"
                    onClick={() => navigate(`/decks/${deck.deck_id}/edit`)}
                  >
                    查看
                  </Button>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

