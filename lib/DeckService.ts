import type { SupabaseClient } from "@supabase/supabase-js";
import { supabase } from "./supabaseClient";

export type DeckItem = { card_id?: string; position?: number };

export type DeckRow = {
    id: string;
    title: string;
    description?: string | null;
    items?: { items?: DeckItem[] };
    created_at?: string | null;
    updated_at?: string | null;
    is_deleted?: boolean | null;
};

export type DeckStat = {
    deck_id: string;
    deck_name: string;
    deck_created_at?: string | null;
    item_count: number;
    learned_count?: number;
    due_count?: number;
    recent_unlearned_count?: number;
    ease_sum: number;
};

export type CreateDeckInput = {
    title: string;
    description?: string | null;
    items?: { items?: DeckItem[] };
};

export type UpdateDeckInput = Partial<{
    title: string;
    description: string | null;
    items: { items?: DeckItem[] };
    is_deleted: boolean;
}>;

type ListOptions = {
    includeDeleted?: boolean;
};

export class DeckService {
    private lastDeckMutationAt = 0;
    private deckByIdCache = new Map<string, DeckRow>();

    constructor(private supabase: SupabaseClient) {}

    async createDeck(input: CreateDeckInput): Promise<DeckRow> {
        const { data, error } = await this.supabase
            .from("decks")
            .insert(input)
            .select()
            .single();
        if (error) throw error;
        this.lastDeckMutationAt = Date.now();
        if (data?.id) {
            this.deckByIdCache.set(data.id, data as DeckRow);
        }
        return data as DeckRow;
    }

    async createIfNotExists(title: string, description?: string | null): Promise<DeckRow> {
        const existing = await this.getDeckByTitle(title);
        if (existing) return existing;
        return this.createDeck({ title, description: description ?? null });
    }

    async updateDeck(deckId: string, patch: UpdateDeckInput): Promise<DeckRow> {
        const { data, error } = await this.supabase
            .from("decks")
            .update(patch)
            .eq("id", deckId)
            .select()
            .single();
        if (error) throw error;
        this.lastDeckMutationAt = Date.now();
        if (data?.id) {
            this.deckByIdCache.set(data.id, data as DeckRow);
        }
        return data as DeckRow;
    }

    async deleteDeck(deckId: string): Promise<void> {
        const { error } = await this.supabase
            .from("decks")
            .update({ is_deleted: true })
            .eq("id", deckId);
        if (error) throw error;
        this.lastDeckMutationAt = Date.now();
        this.deckByIdCache.delete(deckId);
    }

    async getDeckById(deckId: string): Promise<DeckRow | null> {
        const cached = this.deckByIdCache.get(deckId);
        if (cached) return cached;
        const { data, error } = await this.supabase
            .from("user_active_decks")
            .select("*")
            .eq("id", deckId)
            .maybeSingle();
        if (error) throw error;
        const deck = (data as DeckRow) ?? null;
        if (deck?.id) {
            this.deckByIdCache.set(deck.id, deck);
        }
        return deck;
    }

    async getDeckByTitle(title: string, _opts: ListOptions = {}): Promise<DeckRow | null> {
        const { data, error } = await this.supabase
            .from("user_active_decks")
            .select("*")
            .eq("title", title)
            .maybeSingle();
        if (error) throw error;
        return (data as DeckRow) ?? null;
    }

    async listDecksByPrefix(prefix: string, _opts: ListOptions = {}): Promise<DeckRow[]> {
        const hasPrefix = Boolean(prefix && prefix.trim());
        const query = this.supabase.from("user_active_decks").select("*");
        if (hasPrefix) {
            query.or(`title.eq.${prefix},title.ilike.${prefix}/%`);
        }
        const { data, error } = await query.order("title", { ascending: true });
        if (error) throw error;
        return (data as DeckRow[]) ?? [];
    }

    // getCardIds 已移除：请直接从 DeckRow.items 读取

    async fetchDeckStats(): Promise<DeckStat[]> {
        const { data, error } = await this.supabase
            .from("user_deck_stats_view")
            .select("deck_id, deck_name, item_count, learned_count, due_count, recent_unlearned_count, ease_sum")
            .order("deck_name", { ascending: true });
        if (error) throw error;
        return (data as DeckStat[]) ?? [];
    }

    async isRealDeck(path: string): Promise<boolean> {
        const trimmed = path.trim();
        if (!trimmed) return false;
        const { data, error } = await this.supabase
            .from("user_active_decks")
            .select("id")
            .eq("title", trimmed)
            .maybeSingle();
        if (error) throw error;
        return Boolean(data?.id);
    }

    async isDeckPathOccupied(path: string): Promise<boolean> {
        const trimmed = path.trim();
        if (!trimmed) return false;
        const { data, error } = await this.supabase
            .from("user_active_decks")
            .select("id")
            .or(`title.eq.${trimmed},title.ilike.${trimmed}/%`)
            .limit(1);
        if (error) throw error;
        return Boolean((data ?? []).length);
    }

    async addCards(deckId: string, cardIds: string[]): Promise<void> {
        if (!cardIds.length) return;
        const deck = await this.getDeckById(deckId);
        if (!deck) return;
        const items = (deck.items?.items ?? []).slice();
        const existing = new Set(items.map((it) => it.card_id).filter(Boolean) as string[]);
        const next = [
            ...items,
            ...cardIds
                .filter((id) => id && !existing.has(id))
                .map((id) => ({ card_id: id })),
        ];
        await this.updateDeck(deckId, { items: { items: next } });
    }

    async removeCards(deckId: string, cardIds: string[]): Promise<void> {
        if (!cardIds.length) return;
        const deck = await this.getDeckById(deckId);
        if (!deck) return;
        const removeSet = new Set(cardIds);
        const items = (deck.items?.items ?? []).filter((it) => !it.card_id || !removeSet.has(it.card_id));
        await this.updateDeck(deckId, { items: { items } });
    }

    async replaceCards(deckId: string, cardIds: string[]): Promise<void> {
        const items = cardIds.map((id) => ({ card_id: id }));
        await this.updateDeck(deckId, { items: { items } });
    }

    getDeckMutationTimestamp(): number {
        return this.lastDeckMutationAt;
    }

    // WrongBook 相关逻辑已迁移回 lib/WrongBook.ts
}

export const theDeckService = new DeckService(supabase);
