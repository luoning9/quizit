import { supabase } from "./supabaseClient";
import { theDeckService, type DeckRow, type DeckStat } from "./DeckService";

export type DeckTreeNode = {
    name: string;
    fullPath: string;
    deckTitle?: string;
    deckDescription?: string;
    accessTitle?: string;
    children: DeckTreeNode[];
    deckCount: number;
    totalItems: number;
    totalEaseFactor: number;
    learnedCount: number;
    dueCount: number;
    recentUnlearnedCount: number;
    isDeck: boolean;
    deckId: string;
    isOwned: boolean;
};

function createDeckTreeNode(name: string, fullPath: string, accessTitle = fullPath): DeckTreeNode {
    return {
        name,
        fullPath,
        deckTitle: "",
        deckDescription: "",
        accessTitle,
        children: [],
        deckCount: 0,
        totalItems: 0,
        totalEaseFactor: 0,
        learnedCount: 0,
        dueCount: 0,
        recentUnlearnedCount: 0,
        isDeck: false,
        deckId: "",
        isOwned: false,
    };
}

function createRootNode(): DeckTreeNode {
    return createDeckTreeNode("", "", "");
}

function splitPath(path: string): string[] {
    return path
        .trim()
        .split("/")
        .map((part) => part.trim())
        .filter(Boolean);
}

function isPublicAccessPath(path: string): boolean {
    return /^@[0-9a-f]{8}\//i.test(path.trim());
}

function buildDisplayPathSegments(accessPath: string): Array<{ displayPart: string; accessPrefix: string }> {
    const parts = splitPath(accessPath);
    if (!parts.length) return [];

    const isPublic = isPublicAccessPath(accessPath);
    if (!isPublic || parts.length < 2) {
        return parts.map((part, idx) => ({
            displayPart: part,
            accessPrefix: parts.slice(0, idx + 1).join("/"),
        }));
    }

    const segments: Array<{ displayPart: string; accessPrefix: string }> = [
        {
            displayPart: `@${parts[1]}`,
            accessPrefix: parts.slice(0, 2).join("/"),
        },
    ];

    for (let i = 2; i < parts.length; i += 1) {
        segments.push({
            displayPart: parts[i],
            accessPrefix: parts.slice(0, i + 1).join("/"),
        });
    }

    return segments;
}

function normalizeAccessPrefix(path: string): string {
    return path.trim().replace(/^@[0-9a-f]{8}\//i, "");
}

function matchesNodePath(node: DeckTreeNode, target: string, normalizedTarget: string): boolean {
    return (
        node.fullPath === target ||
        node.accessTitle === target ||
        node.deckTitle === target ||
        normalizeAccessPrefix(node.fullPath) === normalizedTarget ||
        normalizeAccessPrefix(node.accessTitle ?? "") === normalizedTarget ||
        normalizeAccessPrefix(node.deckTitle ?? "") === normalizedTarget
    );
}

function findNodeByPath(root: DeckTreeNode, path: string): DeckTreeNode | null {
    const target = path.trim();
    if (!target) return root;

    const normalizedTarget = normalizeAccessPrefix(target);
    const stack: DeckTreeNode[] = [root];
    while (stack.length) {
        const node = stack.pop()!;
        if (matchesNodePath(node, target, normalizedTarget)) {
            return node;
        }
        stack.push(...node.children);
    }

    return null;
}

function hasOccupiedNodePath(root: DeckTreeNode, path: string): boolean {
    const target = path.trim();
    if (!target) return false;

    const stack: DeckTreeNode[] = [root];
    while (stack.length) {
        const node = stack.pop()!;
        if (node.fullPath === target || node.accessTitle === target) {
            return true;
        }
        if (node.fullPath.startsWith(`${target}/`) || node.accessTitle?.startsWith(`${target}/`)) {
            return true;
        }
        stack.push(...node.children);
    }
    return false;
}

function cloneTree(root: DeckTreeNode): { root: DeckTreeNode; nodeMap: Map<string, DeckTreeNode> } {
    const nodeMap = new Map<string, DeckTreeNode>();

    const cloneNode = (node: DeckTreeNode): DeckTreeNode => {
        const next: DeckTreeNode = {
            name: node.name,
            fullPath: node.fullPath,
            deckTitle: node.deckTitle ?? "",
            deckDescription: node.deckDescription ?? "",
            accessTitle: node.accessTitle ?? node.fullPath,
            children: [],
            deckCount: node.deckCount,
            totalItems: 0,
            totalEaseFactor: 0,
            learnedCount: 0,
            dueCount: 0,
            recentUnlearnedCount: 0,
            isDeck: node.isDeck,
            deckId: node.deckId,
            isOwned: node.isOwned,
        };
        nodeMap.set(next.fullPath, next);
        if (next.accessTitle && next.accessTitle !== next.fullPath) {
            nodeMap.set(next.accessTitle, next);
        }
        for (const child of node.children) {
            next.children.push(cloneNode(child));
        }
        return next;
    };

    return { root: cloneNode(root), nodeMap };
}

function appendDeckPath(
    root: DeckTreeNode,
    nodeMap: Map<string, DeckTreeNode>,
    accessPath: string,
    deck: DeckRow,
    currentUserId: string | null
) {
    const parts = buildDisplayPathSegments(accessPath);
    if (!parts.length) return;

    let current = root;
    let currentPath = "";
    let currentAccessPath = "";
    const pathNodes: DeckTreeNode[] = [root];

    for (const part of parts) {
        currentPath = currentPath ? `${currentPath}/${part.displayPart}` : part.displayPart;
        currentAccessPath = part.accessPrefix;
        let next = current.children.find((child) => child.name === part.displayPart);
        if (!next) {
            next = createDeckTreeNode(part.displayPart, currentPath, currentAccessPath);
            current.children.push(next);
            nodeMap.set(currentPath, next);
            nodeMap.set(currentAccessPath, next);
        }
        current = next;
        pathNodes.push(current);
    }

    for (const node of pathNodes) {
        node.deckCount += 1;
    }

    const leaf = current;
    leaf.isDeck = true;
    leaf.deckId = deck.id;
    leaf.deckTitle = deck.title;
    leaf.deckDescription = deck.description ?? "";
    leaf.accessTitle = accessPath;
    leaf.isOwned = Boolean(currentUserId && deck.owner_id === currentUserId);
}

function appendStatPath(
    root: DeckTreeNode,
    nodeMap: Map<string, DeckTreeNode>,
    row: DeckStat
) {
    const accessPath = (row.access_title ?? row.deck_name ?? "").trim();
    if (!accessPath) return;

    const parts = splitPath(accessPath);
    if (!parts.length) return;

    const pathNodes: DeckTreeNode[] = [root];
    let currentPath = "";

    for (const part of buildDisplayPathSegments(accessPath)) {
        currentPath = currentPath ? `${currentPath}/${part.displayPart}` : part.displayPart;
        const node = nodeMap.get(currentPath);
        const accessNode = nodeMap.get(part.accessPrefix);
        const resolvedNode = node ?? accessNode;
        if (!resolvedNode) return;
        pathNodes.push(resolvedNode);
    }

    const items = row.item_count ?? 0;
    const learned = row.learned_count ?? 0;
    const due = row.due_count ?? 0;
    const ease = row.ease_sum ?? 0;
    const recentUnlearned = row.recent_unlearned_count ?? 0;

    for (const node of pathNodes) {
        node.totalItems += items;
        node.totalEaseFactor += ease;
        node.learnedCount += learned;
        node.dueCount += due;
        node.recentUnlearnedCount += recentUnlearned;
    }

    const leaf = pathNodes[pathNodes.length - 1];
    leaf.deckId = row.deck_id;
    leaf.isDeck = true;
    leaf.isOwned = row.is_owned ?? leaf.isOwned;
    leaf.deckTitle = row.deck_title ?? row.deck_name ?? leaf.deckTitle ?? "";
    leaf.deckDescription = leaf.deckDescription ?? "";
    leaf.accessTitle = accessPath;
}

export function buildDeckTreeStructure(
    decks: DeckRow[],
    currentUserId: string | null
): DeckTreeNode {
    const root = createRootNode();
    const nodeMap = new Map<string, DeckTreeNode>();
    nodeMap.set("", root);

    for (const deck of decks) {
        const accessPath = (deck.access_title ?? deck.title ?? "").trim();
        if (!accessPath) continue;
        appendDeckPath(root, nodeMap, accessPath, deck, currentUserId);
    }

    return root;
}

export async function loadDeckTreeStructure(): Promise<DeckTreeNode> {
    const [decks, authResult] = await Promise.all([
        theDeckService.fetchAccessibleDecks(),
        supabase.auth.getUser(),
    ]);

    return buildDeckTreeStructure(decks, authResult.data.user?.id ?? null);
}

export async function loadDeckStats(): Promise<DeckStat[]> {
    return theDeckService.fetchDeckStats();
}

export function applyDeckStatsToTree(root: DeckTreeNode, stats: DeckStat[]): DeckTreeNode {
    const cloned = cloneTree(root);

    for (const row of stats) {
        appendStatPath(cloned.root, cloned.nodeMap, row);
    }

    return cloned.root;
}

export function findDeckTreeNode(root: DeckTreeNode, path: string): DeckTreeNode | null {
    return findNodeByPath(root, path);
}

export async function isRealDeck(path: string): Promise<boolean> {
    const root = await loadDeckTreeStructure();
    const node = findDeckTreeNode(root, path);
    return Boolean(node?.isDeck);
}

export async function isDeckPathOccupied(path: string): Promise<boolean> {
    const root = await loadDeckTreeStructure();
    return hasOccupiedNodePath(root, path);
}
