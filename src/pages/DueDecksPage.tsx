import React, { useEffect, useState } from "react";
import { supabase } from "../../lib/supabaseClient";
import { Button } from "../components/ui/Button";
import { useNavigate } from "react-router-dom";
import { DeckList, type DeckListItem } from "../components/DeckList";

export default function DueDecksPage() {
  const [decks, setDecks] = useState<DeckListItem[]>([]);
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
        .gt("due_count", 0)
        .order("due_count", { ascending: false });

      if (error) {
        console.error("load due decks error", error);
        setError("加载列表失败");
      } else {
        setDecks((data as DeckListItem[]) ?? []);
      }
      setLoading(false);
    }
    void load();
  }, []);

  function handleLearn(deck: DeckListItem) {
    navigate(`/decks/${encodeURIComponent(deck.deck_name)}/practice`);
  }

  function handleView(deck: DeckListItem) {
    navigate(`/decks/${deck.deck_id}/edit`);
  }

  return (
    <div className="max-w-4xl mx-auto py-8 px-4 space-y-6 text-slate-900 dark:text-slate-100 text-base">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">需要复习的知识主题</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            按待复习数量降序，快速进入复习
          </p>
        </div>
        <Button variant="outline" onClick={() => navigate("/")}>
          返回目录
        </Button>
      </div>

      {loading && (
        <div className="text-base text-slate-500 dark:text-slate-400">
          正在加载…
        </div>
      )}
      {error && (
        <div className="text-base text-red-500 dark:text-red-400">{error}</div>
      )}

      {!loading && !error && (
        <DeckList
          decks={decks}
          onLearn={handleLearn}
          onView={handleView}
          emptyText="暂无数据"
        />
      )}
    </div>
  );
}
