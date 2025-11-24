import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { supabase } from "../../lib/supabaseClient";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { PageHeader } from "../layouts/PageHeader";

interface Deck {
    id: string;
    title: string;
    description: string | null;
    items: { items: { card_id: string }[] };
    updated_at: string | null;
}

export function DeckListPage() {
    const [decks, setDecks] = useState<Deck[]>([]);
    const [loading, setLoading] = useState(true);

    // 新建 deck 输入
    const [newTitle, setNewTitle] = useState("");
    const [newDesc, setNewDesc] = useState("");
    const [creating, setCreating] = useState(false);

    const navigate = useNavigate();

    // 读取所有 deck
    async function loadDecks() {
        setLoading(true);
        const { data, error } = await supabase
            .from("decks")
            .select("id, title, description, items, updated_at")
            .order("updated_at", { ascending: false });

        if (!error) setDecks(data as Deck[]);
        setLoading(false);
    }

    useEffect(() => {
        loadDecks();
    }, []);

    // 新建 deck（仅 title + description）
    async function handleCreateDeck() {
        if (!newTitle.trim()) return;

        setCreating(true);

        const {
            data: { user },
        } = await supabase.auth.getUser();

        if (!user) {
            alert("需要登录才能新建题库。");
            setCreating(false);
            return;
        }

        const { error } = await supabase.from("decks").insert({
            owner_id: user.id,
            title: newTitle.trim(),
            description: newDesc.trim() || null,
            items: { items: [] },
            tags: [],
            subject: null,
            grade: null,
        });

        if (error) {
            console.error(error);
            alert("创建失败");
        } else {
            setNewTitle("");
            setNewDesc("");
            await loadDecks();
        }

        setCreating(false);
    }

    // 编辑 Deck
    async function handleEditDeck(deck: Deck) {
        const title = window.prompt("修改名称：", deck.title);
        if (title === null) return;

        const description = window.prompt(
            "修改描述：",
            deck.description || ""
        );
        if (description === null) return;

        const { error } = await supabase
            .from("decks")
            .update({
                title: title.trim(),
                description: description.trim() || null,
            })
            .eq("id", deck.id);

        if (!error) await loadDecks();
    }

    // 删除
    async function handleDeleteDeck(deck: Deck) {
        const ok = window.confirm(`确定删除题库「${deck.title}」？`);
        if (!ok) return;

        const { error } = await supabase
            .from("decks")
            .delete()
            .eq("id", deck.id);

        if (!error) await loadDecks();
    }

    function formatDate(s: string | null) {
        return s ? new Date(s).toLocaleDateString() : "";
    }

    // 解析标题层级
    function parseTitle(title: string) {
        const parts = title.split("/").map((t) => t.trim()).filter(Boolean);
        return {
            name: parts[parts.length - 1] ?? title,
            path: parts.length > 1 ? parts.slice(0, -1).join(" / ") : null,
        };
    }

    return (
        <div className="space-y-6">
            <PageHeader
                title="闪卡题库"
                subtitle="管理你的所有题库。题库名称支持“/”表示层级结构。"
            />

            {/* 列表部分 */}
            {loading ? (
                <div>加载中…</div>
            ) : decks.length === 0 ? (
                <div className="text-sm text-slate-500">尚无题库，请在下方新建。</div>
            ) : (
                <div className="space-y-3">
                    {decks.map((deck) => {
                        const { name, path } = parseTitle(deck.title);
                        const cardCount = deck.items?.items?.length ?? 0;

                        return (
                            <Card
                                key={deck.id}
                                className="flex flex-col md:flex-row md:items-center md:justify-between gap-3"
                            >
                                <div>
                                    <div className="text-base font-medium">{name}</div>

                                    {path && (
                                        <div className="text-xs text-slate-500 mt-0.5">
                                            {path}
                                        </div>
                                    )}

                                    <div className="text-xs text-slate-500 mt-1">
                                        {cardCount} 张闪卡
                                        {deck.updated_at && (
                                            <> · 更新于：{formatDate(deck.updated_at)}</>
                                        )}
                                    </div>

                                    {deck.description && (
                                        <div className="mt-1 text-xs text-slate-600">
                                            {deck.description}
                                        </div>
                                    )}
                                </div>

                                <div className="flex gap-2 justify-end">
                                    <Button
                                        variant="secondary"
                                        className="text-xs px-3 py-1.5"
                                        onClick={() =>
                                            navigate(`/decks/${encodeURIComponent(deck.title)}/practice`)
                                        }
                                    >
                                        练习
                                    </Button>

                                    <Button
                                        variant="ghost"
                                        className="text-xs px-3 py-1.5"
                                        onClick={() => handleEditDeck(deck)}
                                    >
                                        编辑
                                    </Button>

                                    <Button
                                        variant="ghost"
                                        className="text-xs px-3 py-1.5 text-red-500"
                                        onClick={() => handleDeleteDeck(deck)}
                                    >
                                        删除
                                    </Button>
                                </div>
                            </Card>
                        );
                    })}
                </div>
            )}

            {/* 新建表单（在列表底部） */}
            <Card id="deck-create-form" className="space-y-3 mt-8">
                <div className="text-sm font-medium">新建题库</div>

                <input
                    className="rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand/40 w-full"
                    placeholder="标题（支持 / 分层，例如：初中物理/八年级/声现象）"
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                />

                <textarea
                    className="rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand/40 w-full"
                    placeholder="描述（可选）"
                    rows={2}
                    value={newDesc}
                    onChange={(e) => setNewDesc(e.target.value)}
                />

                <div className="flex justify-end">
                    <Button
                        variant="primary"
                        disabled={creating || !newTitle.trim()}
                        onClick={handleCreateDeck}
                    >
                        {creating ? "创建中…" : "新建题库"}
                    </Button>
                </div>
            </Card>
        </div>
    );
}