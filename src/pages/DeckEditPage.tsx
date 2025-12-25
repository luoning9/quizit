import React, {useEffect, useRef, useState} from "react";
import {useNavigate, useParams} from "react-router-dom";
import {supabase} from "../../lib/supabaseClient";
import Papa, {type ParseResult} from "papaparse";
import {Button} from "../components/ui/Button.tsx";
import { ConfirmDialog } from "../components/ui/ConfirmDialog.tsx";
import { Trash2, Check, Layers, List, RotateCcw, Image } from "lucide-react";

interface DeckRow {
    id: string;
    title: string;
    description: string | null;
    items: { items: { card_id: string; position: number }[] } | null
}

interface DeckItem {
    card_id: string;
    position: number;
}

interface CardRow {
    id: string;
    front: string;
    back: string;
}

type ImportedCardLite = {
    id?: string;
    front: string;
    back: string;
};

interface JsonCardsShape {
    cards?: Array<{ id?: unknown; front?: unknown; back?: unknown }>;
}

function normalizeJsonCards(
    items: Array<{ id?: unknown; front?: unknown; back?: unknown }>
): ImportedCardLite[] {
    return items
        .map((item): ImportedCardLite => {
            const id = typeof item.id === "string" ? item.id : undefined;
            const front =
                typeof item.front === "string" ? item.front : String(item.front ?? "");
            const back =
                typeof item.back === "string" ? item.back : String(item.back ?? "");
            return {id, front, back};
        })
        .filter((c) => c.front.length > 0 || c.back.length > 0);
}

function decodeEscapedString(s: string): string {
    if (!s) return "";

    // 先把双引号 escape 掉，否则 JSON.parse 会报错
    const escaped = s.replace(/"/g, '\\"');

    try {
        return JSON.parse(`"${escaped}"`);
    } catch {
        return s; // 保底：解析失败则返回原文
    }
}

function normalizeCsvRowKeys(
    row: Record<string, string | undefined>
): Record<string, string> {
    const normalized: Record<string, string> = {};
    Object.entries(row).forEach(([key, value]) => {
        normalized[key.trim().toLowerCase()] = value ?? "";
    });
    return normalized;
}

function parseCardsText(raw: string): ImportedCardLite[] {
    const text = raw.trim();
    if (!text) return [];

    // ① 尝试 JSON
    try {
        const parsed: unknown = JSON.parse(text);

        if (Array.isArray(parsed)) {
            return normalizeJsonCards(parsed);
        }

        if (typeof parsed === "object" && parsed !== null && "cards" in parsed) {
            const obj = parsed as JsonCardsShape;
            if (Array.isArray(obj.cards)) {
                return normalizeJsonCards(obj.cards);
            }
        }
        // 不是我们想要的 JSON 结构 → 走 CSV
    } catch {
        // ignore, 去解析 CSV
    }

    // ② 使用 PapaParse 解析 CSV（front,back）
    const result: ParseResult<Record<string, string | undefined>> =
        Papa.parse<Record<string, string | undefined>>(text, {
            header: true,
            skipEmptyLines: true,
            escapeChar: "\\",
        });

    if (result.errors.length > 0 || !Array.isArray(result.data)) {
        return [];
    }

    const rows: Record<string, string | undefined>[] = result.data;

    return rows
        .map((row: Record<string, string | undefined>): ImportedCardLite => {
            // 支持 front/back 表头大小写、前后空格
            const normalized = normalizeCsvRowKeys(row);
            const frontKey =
                normalized.front ??
                normalized.question ??
                normalized.q ??
                normalized.f ??
                "";
            const backKey =
                normalized.back ??
                normalized.answer ??
                normalized.a ??
                normalized.b ??
                "";
            const front = decodeEscapedString(frontKey);
            const back = decodeEscapedString(backKey);
            return {front, back};
        })
        .filter((c) => c.front.length > 0 || c.back.length > 0);
}

const DeckEditPage: React.FC = () => {
    const {deckId} = useParams<{ deckId: string }>();
    const navigate = useNavigate();

    const [loading, setLoading] = useState(true);
    const [importing, setImporting] = useState(false);
    // 新增：多选 & 删除状态
    const [selectedIds, setSelectedIds] = useState<Set<string>>(
        () => new Set<string>()
    );
    const [deleting, setDeleting] = useState(false);
    const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
    const [showDeleteDeckConfirm, setShowDeleteDeckConfirm] = useState(false);
    const [deletingDeck, setDeletingDeck] = useState(false);

    const [deck, setDeck] = useState<DeckRow | null>(null);
    const [cards, setCards] = useState<CardRow[]>([]);
    const [exportJson, setExportJson] = useState("");
    const [error, setError] = useState<string | null>(null);

    // 可编辑的标题/描述
    const [titleInput, setTitleInput] = useState("");
    const [descriptionInput, setDescriptionInput] = useState("");
    const [saveMetaMessage, setSaveMetaMessage] = useState<string | null>(null);
    const [editingTitle, setEditingTitle] = useState(false);
    const [editingDesc, setEditingDesc] = useState(false);
    const [savingTitle, setSavingTitle] = useState(false);
    const [savingDesc, setSavingDesc] = useState(false);
    const [resetting, setResetting] = useState(false);
    const [showResetConfirm, setShowResetConfirm] = useState(false);
    const titleEditRef = useRef<HTMLDivElement | null>(null);
    const descEditRef = useRef<HTMLDivElement | null>(null);
    const fileInputRef = useRef<HTMLInputElement | null>(null);

    // 1. 载入 deck + cards
    useEffect(() => {
        if (!deckId) return;

        async function loadDeck() {
            setLoading(true);
            setError(null);
            setSaveMetaMessage(null);

            const {data: deckData, error: deckError} = await supabase
                .from("decks")
                .select("id, title, description, items")
                .eq("id", deckId)
                .single();

            if (deckError || !deckData) {
                console.error("load deck error", deckError);
                setError("加载 deck 失败");
                setLoading(false);
                return;
            }

            const typedDeck = deckData as DeckRow;
            setDeck(typedDeck);
            setTitleInput(typedDeck.title ?? "");
            setDescriptionInput(typedDeck.description ?? "");

            const rawItems = (typedDeck.items?.items ?? []) as DeckItem[];
            const cardIds = rawItems.map((it) => it.card_id).filter(Boolean);

            if (cardIds.length === 0) {
                setCards([]);
                setLoading(false);
                return;
            }

            const {data: cardsData, error: cardsError} = await supabase
                .from("cards")
                .select("id, front, back")
                .in("id", cardIds);

            if (cardsError || !cardsData) {
                console.error("load cards error", cardsError);
                setError("加载卡片失败");
                setLoading(false);
                return;
            }

            // 按 deck.items 中的顺序排
            const cardsById = new Map(cardsData.map((c) => [c.id, c]));
            const orderedCards: CardRow[] = rawItems
                .map((it) => cardsById.get(it.card_id))
                .filter((c): c is CardRow => !!c);

            setCards(orderedCards);
            setSelectedIds(new Set<string>());
            setLoading(false);
        }

        void loadDeck();
    }, [deckId]);

    // 标题编辑外点击取消
    useEffect(() => {
        if (!editingTitle) return;
        const handleClickOutside = (e: MouseEvent) => {
            if (!titleEditRef.current) return;
            if (!titleEditRef.current.contains(e.target as Node)) {
                setEditingTitle(false);
            }
        };
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, [editingTitle]);

    // 描述编辑外点击取消
    useEffect(() => {
        if (!editingDesc) return;
        const handleClickOutside = (e: MouseEvent) => {
            if (!descEditRef.current) return;
            if (!descEditRef.current.contains(e.target as Node)) {
                setEditingDesc(false);
            }
        };
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, [editingDesc]);

    async function saveDeckMeta(partial: { title?: string; description?: string | null }) {
        if (!deckId) return false;
        setSaveMetaMessage(null);
        const { error } = await supabase
            .from("decks")
            .update(partial)
            .eq("id", deckId);
        if (error) {
            console.error("update deck meta error", error);
            setSaveMetaMessage("保存失败，请稍后再试。");
            return false;
        }
        setDeck((prev) =>
            prev
                ? {
                    ...prev,
                    ...partial,
                }
                : prev
        );
        setSaveMetaMessage("已保存。");
        return true;
    }

    // 3. 导出：只导出 cards
    // 导出格式示例：
    // {
    //   "version": 1,
    //   "cards": [
    //     { "id": "...", "front": "...", "back": "..." },
    //     ...
    //   ]
    // }
    function handleExport() {
        const payload = {
            version: 1,
            cards: cards.map((c) => ({
                id: c.id,
                front: c.front,
                back: c.back,
            })),
        };
        setExportJson(JSON.stringify(payload.cards, null, 2));
    }

    // 4. 导入
    async function handleImport() {
        if (!deckId) return;
        if (!exportJson.trim()) return;

        setError(null);
        setSaveMetaMessage(null);
        setImporting(true);

        try {
            // 1) 解析文本 → cards（支持 JSON 或 CSV front,back）
            const imported = parseCardsText(exportJson);
            if (imported.length === 0) {
                setError(
                    "导入失败：未解析到任何卡片。请确认是合法 JSON 或包含表头 front,back 的 CSV。"
                );
                setImporting(false);
                return;
            }

            // 2) 获取当前用户（用于 owner_id）
            const {
                data: {user},
                error: userError,
            } = await supabase.auth.getUser();

            if (userError || !user) {
                console.error("getUser error", userError);
                setError("导入失败：无法获取当前用户，请先登录。");
                setImporting(false);
                return;
            }

            // 根据是否包含 id 分为更新和新增
            const toUpdate = imported.filter((c) => c.id);
            const toInsert = imported.filter((c) => !c.id);

            // 3) 逐条更新已有卡片（只更新 front/back）
            const updatedCards: CardRow[] = [];
            const missingIds: string[] = [];
            for (const card of toUpdate) {
                const {data, error} = await supabase
                    .from("cards")
                    .update({
                        front: card.front,
                        back: card.back,
                    })
                    .eq("id", card.id!)
                    .select("id, front, back");

                if (error) {
                    console.error("update card error", error);
                    setError("导入失败：更新已有卡片时出现错误。");
                    setImporting(false);
                    return;
                }

                if (!data || data.length === 0) {
                    missingIds.push(card.id!);
                    continue;
                }

                // 取第一条（id 唯一）
                const updated = data[0];
                updatedCards.push(updated as CardRow);
            }

            // 4) 插入新的 cards（card_type 统一为 basic）
            let insertedCards: CardRow[] = [];
            if (toInsert.length > 0) {
                const insertPayload = toInsert.map((c) => ({
                    front: c.front,
                    back: c.back,
                    card_type: "basic" as const,
                }));

                const {data, error: insertError} = await supabase
                    .from("cards")
                    .insert(insertPayload)
                    .select("id, front, back");

                if (insertError || !data) {
                    console.error("insert cards error", insertError);
                    setError("导入失败：写入 cards 表时出现错误。");
                    setImporting(false);
                    return;
                }

                insertedCards = data as CardRow[];
            }

            // 5) 构造新的 deck.items：仅追加新增的卡片，保留原顺序
            const prevItems = ((deck?.items?.items ?? []) as DeckItem[]);
            const startPos = prevItems.length + 1;

            const appendedItems: DeckItem[] = insertedCards.map((c, index) => ({
                card_id: c.id,
                position: startPos + index,
            }));

            const newItemsArray = [...prevItems, ...appendedItems];
            const newItemsJson = {items: newItemsArray};

            const {error: updateDeckError} = await supabase
                .from("decks")
                .update({items: newItemsJson})
                .eq("id", deckId);

            if (updateDeckError) {
                console.error("update deck items error", updateDeckError);
                setError("导入部分成功，但更新 deck.items 失败。");
                setImporting(false);
                return;
            }

            // 6) 更新本地状态：deck.items + cards 列表
            setDeck((prev) =>
                prev
                    ? {
                        ...prev,
                        items: newItemsJson,
                    }
                    : prev
            );

            // 旧的 cards 更新 front/back；末尾追加新插入的 cards
            setCards((prev) => {
                const updatedMap = new Map(updatedCards.map((c) => [c.id, c]));
                const next = prev.map((c) => updatedMap.get(c.id) ?? c);
                return [...next, ...insertedCards];
            });

            setSelectedIds(new Set<string>()); // 如果你有选中逻辑，顺便清空
            setExportJson("");
            setError(null);
            const parts = [];
            if (updatedCards.length > 0) {
                parts.push(`更新 ${updatedCards.length} 张`);
            }
            if (insertedCards.length > 0) {
                parts.push(`追加 ${insertedCards.length} 张`);
            }
            if (missingIds.length > 0) {
                parts.push(`忽略 ${missingIds.length} 张未找到的 id`);
            }
            setSaveMetaMessage(`导入完成：${parts.join("，")}。`);
            setImporting(false);
        } catch (e) {
            console.error(e);
            setError("导入失败：出现未知错误。");
            setImporting(false);
        }
    }

    function handleImportFileClick() {
        fileInputRef.current?.click();
    }

    function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
        const file = e.target.files?.[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (ev) => {
            const text = ev.target?.result;
            if (typeof text === "string") {
                setExportJson(text);
            } else {
                setError("无法读取文件内容。");
            }
        };
        reader.onerror = () => {
            setError("读取文件失败，请重试。");
        };
        reader.readAsText(file, "utf-8");
        // 清空，方便下次选择同一文件
        e.target.value = "";
    }

// 5. 切换某张卡是否选中
    function toggleSelectCard(id: string) {
        setSelectedIds((prev) => {
            const next = new Set(prev);
            if (next.has(id)) {
                next.delete(id);
            } else {
                next.add(id);
            }
            return next;
        });
    }

    function handleToggleSelectAll() {
        setSelectedIds((prev) => {
            // 已全部选中 → 清空
            if (prev.size === cards.length && cards.length > 0) {
                return new Set<string>();
            }
            // 否则 → 选中当前列表所有卡片
            return new Set<string>(cards.map((c) => c.id));
        });
    }

    async function handleResetDeckStats() {
        if (!deckId) return;
        setResetting(true);
        setError(null);
        setSaveMetaMessage(null);
        try {
            const { data: userData, error: userErr } = await supabase.auth.getUser();
            const user = userData?.user;
            if (userErr || !user) {
                setError("未登录，无法重置学习记录。");
                return;
            }
            const cardIds = ((deck?.items?.items ?? []) as DeckItem[])
                .map((it) => it.card_id)
                .filter(Boolean);
            if (cardIds.length === 0) {
                setSaveMetaMessage("当前 deck 没有可重置的卡片。");
                return;
            }
            const { error: delErr } = await supabase
                .from("card_stats")
                .delete()
                .eq("user_id", user.id)
                .in("card_id", cardIds);
            if (delErr) {
                console.error("reset card_stats error", delErr);
                setError("重置失败，请稍后再试。");
                return;
            }
            setSaveMetaMessage("已重置当前 deck 的学习记录。");
        } finally {
            setResetting(false);
            setShowResetConfirm(false);
        }
    }

// 6. 删除选中卡片
    async function handleDeleteSelected() {
        if (!deckId) return;
        if (selectedIds.size === 0) return;

        setDeleting(true);
        setError(null);
        setSaveMetaMessage(null);

        try {
            const ids = Array.from(selectedIds);

            // 1) 只更新 deck.items：过滤掉这些 card_id
            const prevItems = ((deck?.items?.items ?? []) as DeckItem[]);
            const filteredItems = prevItems.filter(
                (it) => !ids.includes(it.card_id)
            );
            const newItemsJson = { items: filteredItems };

            const { error: updateDeckError } = await supabase
                .from("decks")
                .update({ items: newItemsJson })
                .eq("id", deckId);

            if (updateDeckError) {
                console.error(
                    "update deck items after delete error",
                    updateDeckError
                );
                setError("更新 deck 中的卡片列表失败。");
                setDeleting(false);
                return;
            }

            // 2) 更新本地状态：deck + cards 列表 + 选中状态
            setDeck((prev) =>
                prev
                    ? {
                        ...prev,
                        items: newItemsJson,
                    }
                    : prev
            );
            setCards((prev) => prev.filter((c) => !ids.includes(c.id)));
            setSelectedIds(new Set<string>());

            setError(null);
            setSaveMetaMessage(
                `已从当前 deck 中移除 ${ids.length} 张卡片（cards 表记录保留）。`
            );
            setDeleting(false);
        } catch (e) {
            console.error(e);
            setError("删除失败：出现未知错误。");
            setDeleting(false);
        }
    }

    async function handleDeleteDeck() {
        if (!deckId) return;
        setDeletingDeck(true);
        setError(null);

        const { error: deleteError } = await supabase
            .from("decks")
            .update({ is_deleted: true })
            .eq("id", deckId);

        if (deleteError) {
            console.error("delete deck error", deleteError);
            setError("删除 deck 失败，请稍后再试。");
            setDeletingDeck(false);
            return;
        }

        navigate(`/`);
    }

    if (!deckId) {
        return <div className="text-slate-700 dark:text-slate-200 px-4 py-6">缺少 deckId 参数。</div>;
    }

    if (loading) {
        return <div className="text-slate-700 dark:text-slate-200 px-4 py-6">正在加载 deck…</div>;
    }

    if (error && !deck) {
        return (
            <div className="px-4 py-6 space-y-4">
                <div className="text-sm text-rose-600 border border-rose-200 bg-rose-50 rounded-xl px-3 py-2 dark:text-rose-400 dark:border-rose-500/50 dark:bg-rose-950/40">
                    {error}
                </div>
                <Button
                    type="button"
                    variant="link"
                    className="text-sm px-0 text-emerald-700 hover:text-emerald-800 underline underline-offset-4 dark:text-sky-300 dark:hover:text-sky-200"
                    onClick={() => navigate(-1)}
                >
                    返回
                </Button>
            </div>
        );
    }

    if (!deck) {
        return (
            <div className="px-4 py-6 text-slate-700 dark:text-slate-200">
                未找到对应的 deck。
                <div className="mt-3">
                    <Button
                        type="button"
                        variant="link"
                        className="text-sm px-0 text-emerald-700 hover:text-emerald-800 underline underline-offset-4 dark:text-sky-300 dark:hover:text-sky-200"
                        onClick={() => navigate(-1)}
                    >
                        返回
                    </Button>
                </div>
            </div>
        );
    }
    const isAllSelected =
        cards.length > 0 && selectedIds.size === cards.length;

    return (
        <div className="space-y-6 text-slate-900 dark:text-slate-100 px-4 py-6 w-fit mx-auto">
            {/* 顶部标题区 */}
            <div className="flex items-center justify-between gap-4">
                <div className="flex items-start gap-3 flex-1 min-w-0">
                    <Layers className="w-10 h-10 text-emerald-600 dark:text-emerald-400" />
                    <div className="flex-1 min-w-0 space-y-1">
                        {!editingTitle && (
                            <div
                                className="text-2xl font-semibold truncate cursor-text"
                                onDoubleClick={() => {
                                    setTitleInput(deck?.title ?? "");
                                    setEditingTitle(true);
                                }}
                                title="双击编辑标题"
                            >
                                {deck?.title ?? "[未命名]"}
                            </div>
                        )}
                        {editingTitle && (
                            <div className="flex items-center gap-2 max-w-2xl" ref={titleEditRef}>
                            <input
                                type="text"
                                className="flex-1 rounded-xl bg-white border border-slate-300 px-3 py-2 text-xl font-semibold text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 dark:bg-slate-950/70 dark:border-slate-700 dark:text-slate-100 dark:focus:border-sky-500 dark:focus:ring-sky-300/30"
                                value={titleInput}
                                onChange={(e) => setTitleInput(e.target.value)}
                                onKeyDown={async (e) => {
                                    if (e.key === "Enter") {
                                        e.preventDefault();
                                        const trimmed = titleInput.trim();
                                        if (!trimmed) return;
                                        setSavingTitle(true);
                                        const ok = await saveDeckMeta({ title: trimmed });
                                        setSavingTitle(false);
                                        if (ok) {
                                            setEditingTitle(false);
                                        }
                                    }
                                }}
                                autoFocus
                            />
                            <Button
                                type="button"
                                variant="primary"
                                className="px-3 py-2 text-sm whitespace-nowrap"
                                disabled={savingTitle || !titleInput.trim()}
                                onClick={async () => {
                                    const trimmed = titleInput.trim();
                                    if (!trimmed) return;
                                    setSavingTitle(true);
                                    const ok = await saveDeckMeta({ title: trimmed });
                                    setSavingTitle(false);
                                    if (ok) {
                                        setEditingTitle(false);
                                    }
                                }}
                                    >
                                        {savingTitle ? "保存中…" : <Check className="w-4 h-4" />}
                                    </Button>
                                </div>
                            )}
                        {/* 顶部简介可编辑（紧跟标题） */}
                        <div className="max-w-3xl">
                            <div className="flex items-start gap-2">
                    {!editingDesc && (
                        <div
                            className="flex-1 text-left cursor-text"
                            onDoubleClick={() => {
                                setDescriptionInput(deck?.description ?? "");
                                setEditingDesc(true);
                            }}
                            title="双击编辑简介"
                        >
                            <div className="text-sm text-slate-700 dark:text-slate-200 whitespace-pre-line">
                                {deck?.description ?? "[未填写简介]"}
                            </div>
                        </div>
                    )}
                                {editingDesc && (
                        <div className="flex items-start gap-2 flex-1" ref={descEditRef}>
                            <input
                                className="flex-1 rounded-xl bg-white border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 dark:bg-slate-950/70 dark:border-slate-700 dark:text-slate-100 dark:focus:border-sky-500 dark:focus:ring-sky-300/30"
                                value={descriptionInput}
                                onChange={(e) => setDescriptionInput(e.target.value)}
                                onKeyDown={async (e) => {
                                    if (e.key === "Enter") {
                                        e.preventDefault();
                                        setSavingDesc(true);
                                        const ok = await saveDeckMeta({ description: descriptionInput.trim() || null });
                                        setSavingDesc(false);
                                        if (ok) {
                                            setEditingDesc(false);
                                        }
                                    }
                                }}
                                autoFocus
                            />
                            <Button
                                type="button"
                                variant="primary"
                                className="px-3 py-2 text-sm whitespace-nowrap"
                                disabled={savingDesc}
                                            onClick={async () => {
                                                setSavingDesc(true);
                                                const ok = await saveDeckMeta({ description: descriptionInput.trim() || null });
                                                setSavingDesc(false);
                                                if (ok) {
                                                    setEditingDesc(false);
                                                }
                                            }}
                                        >
                                            {savingDesc ? "保存中…" : <Check className="w-4 h-4" />}
                                        </Button>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <Button
                        type="button"
                        variant="ghost"
                        className="p-2 text-slate-600 hover:text-white hover:bg-slate-600 dark:text-slate-300 dark:hover:text-slate-100 dark:hover:bg-slate-700"
                        onClick={() => navigate(`/decks/${deckId}/resources`)}
                        aria-label="资源管理"
                        title="资源管理"
                    >
                        <Image size={20} />
                    </Button>
                    <Button
                        type="button"
                        variant="ghost"
                        className="p-2 text-red-600 hover:text-white hover:bg-red-600 dark:text-red-400 dark:hover:text-red-100 dark:hover:bg-red-700"
                        onClick={() => setShowDeleteDeckConfirm(true)}
                        aria-label="删除这个 deck"
                    >
                        <Trash2 size={20} />
                    </Button>
                    <Button
                        type="button"
                        variant="ghost"
                        className="p-2 text-amber-600 hover:text-white hover:bg-amber-600 dark:text-amber-300 dark:hover:text-amber-100 dark:hover:bg-amber-700"
                        onClick={() => setShowResetConfirm(true)}
                        aria-label="重置学习记录"
                        title="重置学习记录"
                    >
                        <RotateCcw size={20} />
                    </Button>
                    <Button
                        type="button"
                        variant="link"
                        className="p-3 rounded-full text-sky-500 hover:text-white hover:bg-sky-500 dark:text-sky-300 dark:hover:text-sky-100 dark:hover:bg-sky-700"
                        onClick={() => navigate(`/?path=${encodeURIComponent(deck?.title ?? "")}`)}
                        title="返回列表页"
                    >
                        <List className="w-6 h-6" />
                    </Button>
                </div>
            </div>

            {/* 错误提示（整体） */}
            {error && (
                <div className="text-sm text-rose-600 border border-rose-200 bg-rose-50 rounded-xl px-3 py-2 dark:text-rose-400 dark:border-rose-500/50 dark:bg-rose-950/40">
                    {error}
                </div>
            )}

            {saveMetaMessage && (
                <div className="text-xs text-emerald-600 dark:text-emerald-400 text-center">{saveMetaMessage}</div>
            )}

            {/* 2️⃣ 导入 / 导出 cards */}
            <div className="rounded-2xl border border-slate-200 bg-white/90 p-4 space-y-3 shadow-sm dark:border-slate-700 dark:bg-slate-900/70">
                <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold">导入 / 导出卡片（cards）</div>
                    <div className="space-x-2">
                        <Button
                            variant="link"
                            type="button"
                            onClick={handleExport}
                            className="text-sm"
                        >
                            导出当前 cards
                        </Button>
                        <Button
                            variant="outline"
                            type="button"
                            onClick={handleImport}
                            className="text-sm w-30 font-light"
                            disabled={importing}
                        >
                            {importing ? "导入中..." : "导入这些卡片"}
                        </Button>
                        <Button
                            variant="ghost"
                            type="button"
                            onClick={handleImportFileClick}
                            className="text-sm"
                        >
                            从文件…
                        </Button>
                        <input
                            ref={fileInputRef}
                            type="file"
                            accept=".csv,text/csv"
                            className="hidden"
                            onChange={handleFileSelected}
                        />
                    </div>
                </div>

                <textarea
                    className="w-full h-48 text-xs font-mono bg-white border border-slate-300 rounded-xl p-2 text-slate-900 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 dark:bg-slate-950/80 dark:border-slate-700 dark:text-slate-100"
                    placeholder={`支持两种格式（自动识别）：
① JSON：
[
  { "front": "光在真空中的速度是多少？", "back": "3.0×10^8 m/s" },
  { "front": "声音的传播需要什么？", "back": "介质" }
]

② CSV（必须有表头 front,back）：
front,back
光在真空中的速度是多少？,3.0×10^8 m/s
声音的传播需要什么？,介质
`}
                    value={exportJson}
                    onChange={(e) => setExportJson(e.target.value)}
                />
            </div>

            {/* 3️⃣ 卡片列表（预览 + 多选删除） */}
            <div className="rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-sm dark:border-slate-700 dark:bg-slate-900/70">
                <div className="flex items-center justify-between mb-3">
                    <div className="text-sm font-semibold">
                        卡片预览（{cards.length} 条）
                    </div>
                    <div className="flex items-center gap-2">
        <span className="text-xs text-slate-400">
            已选中：{selectedIds.size} 张
        </span>

                        {/* 全选 / 全不选 */}
                        <Button
                            type="button"
                            variant="ghost"
                            onClick={handleToggleSelectAll}
                            disabled={cards.length === 0}
                            className="px-2 py-1 text-xs text-slate-300 hover:text-slate-50 hover:bg-slate-700/60 disabled:text-slate-500 disabled:hover:bg-transparent"
                        >
                            {isAllSelected ? "全不选" : "全选"}
                        </Button>

                        {/* 删除选中 */}
                        <Button
                            type="button"
                            variant="outline"
                            onClick={() => setShowDeleteConfirm(true)}
                            disabled={deleting || selectedIds.size === 0}
                            className="px-3 py-1.5 text-xs text-rose-300 border-rose-500 hover:bg-rose-500/10 hover:text-rose-100 disabled:text-slate-500 disabled:border-slate-600"
                        >
                            删除选中卡片
                        </Button>
                    </div>
                </div>
                {cards.length === 0 ? (
                    <div className="text-xs text-slate-500">当前 deck 还没有卡片。</div>
                ) : (
                    <ul className="space-y-2 pr-2">
                        {cards.map((c, idx) => (
                            <li
                                key={c.id}
                                className="border border-slate-200 bg-white rounded-xl px-3 py-2 text-xs flex items-start gap-2 shadow-sm dark:border-slate-700 dark:bg-slate-900"
                            >
                                <input
                                    type="checkbox"
                                    className="mt-1 h-3.5 w-3.5 rounded border-slate-500 bg-slate-900"
                                    checked={selectedIds.has(c.id)}
                                    onChange={() => toggleSelectCard(c.id)}
                                />
                                <div className="flex-1">
                                    {/* 顶部：编号 + id（缩短一点防止太长） */}
                                    <div className="flex items-center justify-between mb-1 text-slate-500 dark:text-slate-400">
                                        <span>#{idx + 1}</span>
                                        <span className="text-right break-all">{c.id}</span>
                                    </div>

                                    {/* 主体：左右两栏 front / back */}
                                    <div className="flex gap-3">
                                        <div className="flex-1 min-w-0">
                                            <div className="text-[10px] text-slate-500 mb-0.5">front</div>
                                            <div className="text-slate-900 dark:text-slate-100 whitespace-pre-wrap break-words">
                                                {c.front}
                                            </div>
                                        </div>
                                        <div className="flex-1 min-w-0 border-l border-slate-700 pl-3">
                                            <div className="text-[10px] text-slate-500 mb-0.5">back</div>
                                            <div className="text-slate-800 dark:text-slate-300 whitespace-pre-wrap break-words">
                                                {c.back || <span className="text-slate-500 dark:text-slate-500">（空）</span>}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </li>
                        ))}
                    </ul>
                )}
            </div>
            <ConfirmDialog
                open={showDeleteConfirm}
                title="确认删除选中卡片？"
                description={`将从当前 deck 中移除已选中的 ${selectedIds.size} 张卡片（不会删除 cards 表中的记录）。`}
                confirmLabel={deleting ? "删除中…" : "确认删除"}
                cancelLabel="取消"
                loading={deleting}
                onCancel={() => {
                    if (!deleting) {
                        setShowDeleteConfirm(false);
                    }
                }}
                onConfirm={() => {
                    // 直接调用已有的删除逻辑
                    void handleDeleteSelected();
                    setShowDeleteConfirm(false);
                }}
            />
            <ConfirmDialog
                open={showResetConfirm}
                title="重置学习记录"
                description="是否要重置这个知识点的学习记录？重置操作不可恢复。"
                confirmLabel={resetting ? "重置中…" : "确认重置"}
                cancelLabel="取消"
                loading={resetting}
                onCancel={() => {
                    if (!resetting) setShowResetConfirm(false);
                }}
                onConfirm={() => {
                    void handleResetDeckStats();
                }}
            />
            <ConfirmDialog
                open={showDeleteDeckConfirm}
                title="确认删除整个 Deck？"
                description="删除后将移除当前 deck 及其关联关系（cards 记录保留）。"
                confirmLabel={deletingDeck ? "删除中…" : "确认删除"}
                cancelLabel="取消"
                loading={deletingDeck}
                onCancel={() => {
                    if (!deletingDeck) {
                        setShowDeleteDeckConfirm(false);
                    }
                }}
                onConfirm={() => {
                    void handleDeleteDeck();
                    setShowDeleteDeckConfirm(false);
                }}
            />
        </div>
    );
};

export default DeckEditPage;
