import { supabase } from "./supabaseClient.ts";

/**
 * 将卡片加入指定 deck 的错题本（不存在则创建）。
 * @param deckTitle 原 deck 的标题
 * @param cardId 需要加入的卡片 ID
 */
export async function addCardToWrongBook(deckTitle: string, cardId: string) {
    const wrongDeckTitle = `${deckTitle}/_错题本`;

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
