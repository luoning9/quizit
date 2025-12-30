import { useEffect, useState } from "react";
import { supabase } from "../../lib/supabaseClient";
import { Button } from "../components/ui/Button";
import { useNavigate } from "react-router-dom";
import { DeckList, type DeckListItem } from "../components/DeckList";

export default function NewDecksPage() {
  const [decks, setDecks] = useState<DeckListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isEditMode =
    typeof window !== "undefined" &&
    localStorage.getItem("mode") === "edit";
  const navigate = useNavigate();

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      const { data, error } = await supabase
        .from("user_deck_stats_view")
        .select(
          "deck_id, deck_name, deck_created_at, item_count, learned_count, due_count, recent_unlearned_count"
        )
        .gt("recent_unlearned_count", 0)
        .order("deck_created_at", { ascending: false });

      if (error) {
        console.error("load new decks error", error);
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
          <h1 className="text-2xl font-semibold">新增知识卡片情况</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            按创建时间倒序，方便快速开始学习
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
          onView={isEditMode ? handleView : undefined}
          emptyText="暂无数据"
          actionStyle="icon"
        />
      )}
    </div>
  );
}
