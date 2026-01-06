import { supabase } from "./supabaseClient.ts";

async function resolveWrongBookTitle(deckTitle: string): Promise<string> {
    const trimmed = deckTitle.trim();
    if (!trimmed) return "_错题本";

    const { data: deckMeta, error } = await supabase
        .from("decks")
        .select("id")
        .eq("title", trimmed)
        .maybeSingle();

    if (error) {
        console.error("查询 deck 失败", error);
        return `${trimmed}/_错题本`;
    }

    if (deckMeta?.id) {
        const parentPath = trimmed.split("/").slice(0, -1).filter(Boolean).join("/");
        return parentPath ? `${parentPath}/_错题本` : "_错题本";
    }

    return `${trimmed}/_错题本`;
}

/**
 * 将卡片加入指定 deck 的错题本（不存在则创建）。
 * @param deckTitle 原 deck 的标题
 * @param cardId 需要加入的卡片 ID
 */
export async function addCardToWrongBook(deckTitle: string, cardId: string) {
    const wrongDeckTitle = await resolveWrongBookTitle(deckTitle);

    // 查询是否已有该错题本
    const { data: existingDeck, error: deckQueryErr } = await supabase
        .from("decks")
        .select("id, items, owner_id")
        .eq("title", wrongDeckTitle)
        .maybeSingle();

    if (deckQueryErr) {
        console.error("查询错题本 deck 失败", deckQueryErr);
        return;
    }

    if (existingDeck?.id) {
        // 已存在：追加 cardId（避免重复）
        const items = existingDeck.items ?? { items: [] as any[] };
        const arr = Array.isArray((items as any).items) ? (items as any).items : [];
        const already = arr.some((it: any) => it.card_id === cardId);
        if (already) return;

        const newItems = [...arr, { card_id: cardId }];
        const { error: updateErr } = await supabase
            .from("decks")
            .update({ items: { items: newItems } })
            .eq("id", existingDeck.id);
        if (updateErr) {
            console.error("更新错题本 deck 失败", updateErr);
        }
        return;
    }

    // 不存在：创建新的错题本 deck
    const { data: userData } = await supabase.auth.getUser();
    const owner_id = userData.user?.id ?? null;
    const newDeck = {
        title: wrongDeckTitle,
        items: { items: [{ card_id: cardId }] },
        owner_id,
    };
    const { error: insertErr } = await supabase
        .from("decks")
        .insert(newDeck);
    if (insertErr) {
        console.error("创建错题本 deck 失败", insertErr);
    }
}

/**
 * 根据 deck 标题找到错题本并返回卡片 ID 集合。
 */
export async function fetchWrongBookCardIds(deckTitle: string): Promise<Set<string>> {
    const wrongDeckTitle = await resolveWrongBookTitle(deckTitle);
    const { data: wrongDeck, error: wrongDeckErr } = await supabase
        .from("decks")
        .select("items")
        .eq("title", wrongDeckTitle)
        .maybeSingle();

    if (wrongDeckErr || !wrongDeck) {
        if (wrongDeckErr) {
            console.error("查询错题本 deck 失败", wrongDeckErr);
        }
        return new Set();
    }

    const wrongItems =
        (wrongDeck as { items?: { items?: Array<{ card_id?: string }> } }).items?.items ?? [];
    const ids = wrongItems
        .map((item) => item?.card_id)
        .filter((id): id is string => Boolean(id));
    return new Set(ids);
}
