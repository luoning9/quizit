import { theDeckService } from "./DeckService";
import { isRealDeck } from "./deckTree";

async function resolveWrongBookTitle(deckTitle: string): Promise<string> {
    const trimmed = deckTitle.trim();
    if (!trimmed) return "_错题本";
    if (await isRealDeck(trimmed)) {
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

    try {
        const deck = await theDeckService.createIfNotExists(wrongDeckTitle);
        await theDeckService.addCards(deck.id, [cardId]);
    } catch (err) {
        console.error("更新错题本 deck 失败", err);
    }
}

/**
 * 根据 deck 标题找到错题本并返回卡片 ID 集合。
 */
export async function fetchWrongBookCardIds(deckTitle: string): Promise<Set<string>> {
    const wrongDeckTitle = await resolveWrongBookTitle(deckTitle);
    try {
        const wrongDeck = await theDeckService.getDeckByTitle(wrongDeckTitle);
        if (!wrongDeck) return new Set();
        const wrongItems =
            (wrongDeck as { items?: { items?: Array<{ card_id?: string }> } }).items?.items ?? [];
        const ids = wrongItems
            .map((item) => item?.card_id)
            .filter((id): id is string => Boolean(id));
        return new Set(ids);
    } catch (err) {
        console.error("查询错题本 deck 失败", err);
        return new Set();
    }
}

export async function fetchWrongBookDeck(deckTitle: string) {
    const wrongDeckTitle = await resolveWrongBookTitle(deckTitle);
    try {
        return await theDeckService.getDeckByTitle(wrongDeckTitle);
    } catch (err) {
        console.error("查询错题本 deck 失败", err);
        return null;
    }
}
