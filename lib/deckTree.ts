import { theDeckService, type DeckStat } from "./DeckService";

type DeckTreeCache = {
    value: { root: DeckTreeNode; nodeMap: Map<string, DeckTreeNode> } | null;
    fetchedAt: number;
    mutationAt: number;
};

const CACHE_TTL_MS = 3_333_000;
let deckTreeCache: DeckTreeCache = {
    value: null,
    fetchedAt: 0,
    mutationAt: 0,
};

export function invalidateDeckTreeCache() {
    deckTreeCache = { value: null, fetchedAt: 0, mutationAt: 0 };
}

export function isRealDeckSync(path: string): boolean {
    const target = path.trim();
    if (!target) return false;
    const node = deckTreeCache.value?.nodeMap.get(target);
    return Boolean(node?.isDeck);
}

export function isDeckPathOccupiedSync(path: string): boolean {
    const target = path.trim();
    if (!target) return false;
    if (deckTreeCache.value?.nodeMap.has(target)) return true;
    const prefix = `${target}/`;
    for (const key of deckTreeCache.value?.nodeMap.keys() ?? []) {
        if (key.startsWith(prefix)) return true;
    }
    return false;
}

export async function isRealDeck(path: string): Promise<boolean> {
    await loadDeckTree();
    return isRealDeckSync(path);
}

export async function isDeckPathOccupied(path: string): Promise<boolean> {
    await loadDeckTree();
    return isDeckPathOccupiedSync(path);
}

export type DeckTreeNode = {
    name: string;
    fullPath: string;
    children: DeckTreeNode[];
    deckCount: number;
    totalItems: number;
    totalEaseFactor: number;
    learnedCount: number;
    dueCount: number;
    recentUnlearnedCount: number;
    isDeck: boolean;
    deckId: string;
};

export function buildDeckTree(
    stats: DeckStat[]
): { root: DeckTreeNode; nodeMap: Map<string, DeckTreeNode> } {
    const root: DeckTreeNode = {
        name: "",
        fullPath: "",
        children: [],
        deckCount: 0,
        totalItems: 0,
        totalEaseFactor: 0,
        learnedCount: 0,
        dueCount: 0,
        recentUnlearnedCount: 0,
        isDeck: false,
        deckId: "",
    };
    const nodeMap = new Map<string, DeckTreeNode>();

    const ensureChild = (parent: DeckTreeNode, name: string): DeckTreeNode => {
        const existing = parent.children.find((c) => c.name === name);
        if (existing) return existing;

        const fullPath = parent.fullPath ? `${parent.fullPath}/${name}` : name;
        const node: DeckTreeNode = {
            name,
            fullPath,
            children: [],
            deckCount: 0,
            totalItems: 0,
            totalEaseFactor: 0,
            learnedCount: 0,
            dueCount: 0,
            recentUnlearnedCount: 0,
            isDeck: false,
            deckId: "",
        };
        parent.children.push(node);
        nodeMap.set(fullPath, node);
        return node;
    };

    for (const row of stats) {
        if (!row.deck_name) continue;
        const parts = row.deck_name.split("/").filter(Boolean);
        if (parts.length === 0) continue;
        let current = root;
        let acc = "";
        const pathNodes: DeckTreeNode[] = [root];
        for (const part of parts) {
            acc = acc ? `${acc}/${part}` : part;
            current = ensureChild(current, part);
            pathNodes.push(current);
        }

        const items = row.item_count ?? 0;
        const learned = row.learned_count ?? 0;
        const due = row.due_count ?? 0;
        const ease = row.ease_sum ?? 0;
        const recentUnlearned = row.recent_unlearned_count ?? 0;

        pathNodes.forEach((node) => {
            node.deckCount += 1;
            node.totalItems += items;
            node.totalEaseFactor += ease;
            node.learnedCount += learned;
            node.dueCount += due;
            node.recentUnlearnedCount += recentUnlearned;
        });

        current.deckId = row.deck_id;
        current.isDeck = row.deck_id != null;
    }

    return { root, nodeMap };
}

export async function loadDeckTree(force = false) {
    const mutationAt = theDeckService.getDeckMutationTimestamp();
    const now = Date.now();
    if (
        !force &&
        deckTreeCache.value &&
        now - deckTreeCache.fetchedAt < CACHE_TTL_MS &&
        deckTreeCache.mutationAt >= mutationAt
    ) {
        return deckTreeCache.value;
    }
    const stats = await theDeckService.fetchDeckStats();
    const built = buildDeckTree(stats);
    deckTreeCache = {
        value: built,
        fetchedAt: now,
        mutationAt,
    };
    return built;
}
