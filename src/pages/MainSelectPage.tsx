import {useEffect, useMemo, useState} from "react";
import {supabase} from "../../lib/supabaseClient";
import {Button} from "../components/ui/Button";
import {Folder, Layers, PencilLine} from "lucide-react";
import {DeckStatus} from "../components/DeckStatus";
import {useNavigate, useOutletContext, useSearchParams} from "react-router-dom";

/**
 * 来自 view：user_deck_folder_view 的记录
 * path            目录路径，如 "A", "A/B", "Physics/Grade8"
 * deck_count      该节点下（含子节点）的 deck 数量
 * total_items     该节点下（含子节点）的 items 总数
 * total_ease_factor 该节点下所有已学习卡片的 ease_factor 之和
 */
type DeckStat = {
    deck_id: string;
    deck_name: string;
    deck_created_at?: string | null;
    item_count: number;
    learned_count?: number;
    due_count?: number;
    recent_unlearned_count?: number;
    ease_sum: number;
};

interface DeckTreeNode {
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
}

interface QuizTemplate {
    id: string;
    title: string;
    description: string | null;
    deck_name: string | null;
    item_count: number;
    attempt_count: number;
    last_score: number | null;
    last_attempt_at: string | null;
}

type NavContext = {
    setNavDueCount?: (n: number) => void;
    setNavRecentNewCount?: (n: number) => void;
};

// 根据 view 的 path 构造目录树，并收集所有路径前缀
function buildDeckTree(stats: DeckStat[]): { root: DeckTreeNode; deckNameSet: Set<string> } {
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
    const deckNameSet = new Set<string>();

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
        return node;
    };

    for (const row of stats) {
        if (!row.deck_name) continue;
        const parts = row.deck_name.split("/").filter(Boolean);
        if (parts.length === 0) continue;

        // 收集所有前缀路径
        let acc = "";
        parts.forEach((part, idx) => {
            acc = idx === 0 ? part : `${acc}/${part}`;
            deckNameSet.add(acc);
        });

        let current = root;
        const pathNodes: DeckTreeNode[] = [root];
        for (const part of parts) {
            current = ensureChild(current, part);
            pathNodes.push(current);
        }

        const items = row.item_count ?? 0;
        const learned = row.learned_count ?? 0;
        const due = row.due_count ?? 0;
        const ease = row.ease_sum ?? 0;
        const recentUnlearned = row.recent_unlearned_count ?? 0;

        // 累加到路径上的每个节点（含自身）
        pathNodes.forEach((node) => {
            node.deckCount += 1;
            node.totalItems += items;
            node.totalEaseFactor += ease;
            node.learnedCount += learned;
            node.dueCount += due;
            node.recentUnlearnedCount += recentUnlearned;
        });

        // 叶子节点标记 deck 信息
        current.deckId = row.deck_id;
        current.isDeck = row.deck_id != null;
    }

    return { root, deckNameSet };
}

// 根据路径查找目录节点
function findNodeByPath(root: DeckTreeNode, path: string): DeckTreeNode {
    if (!path) return root;
    const parts = path.split("/").filter(Boolean);
    let current = root;

    for (const seg of parts) {
        const next = current.children.find((c) => c.name === seg);
        if (!next) return root;
        current = next;
    }
    return current;
}

function calcProgress(node: DeckTreeNode): number {
    if (!node || node.totalItems === 0) return 0;
    return Math.round((node.totalEaseFactor / (node.totalItems * 4)) * 100);
}

function parseLeadingNumber(name: string): number | null {
    const head = name.split(/[_\s]/)[0] || "";
    const direct = Number(head);
    if (!Number.isNaN(direct)) return direct;

    const digitMap: Record<string, number> = {
        "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    };

    if (digitMap[head] != null) return digitMap[head];

    const matchTens = head.match(/^([一二三四五六七八九])?十([一二三四五六七八九])?$/);
    if (matchTens) {
        const tens = matchTens[1] ? digitMap[matchTens[1]] : 1;
        const ones = matchTens[2] ? digitMap[matchTens[2]] : 0;
        return tens * 10 + ones;
    }

    return null;
}

export function MainSelectPage() {
    const [searchParams, setSearchParams] = useSearchParams();
    // 用 URL 里的 ?path=... 作为初始值，没有就用 "/"
    const initialPath = searchParams.get("path") || "";

    const navigate = useNavigate();
    const {setNavDueCount, setNavRecentNewCount} = useOutletContext<NavContext>();
    const [deckStats, setDeckStats] = useState<DeckStat[]>([]);
    const [loading, setLoading] = useState(true);
    const [selectedPath, setSelectedPath] = useState(initialPath);
    const [quizTemplates, setQuizTemplates] = useState<QuizTemplate[]>([]);

    // 2️⃣ 当 selectedPath 改变时，把它写回 URL
    useEffect(() => {
        // 根路径可以选择不写 path 参数
        if (!selectedPath) {
            setSearchParams((prev) => {
                const next = new URLSearchParams(prev);
                next.delete("path");
                return next;
            });
        } else {
            setSearchParams((prev) => {
                const next = new URLSearchParams(prev);
                next.set("path", selectedPath);
                return next;
            });
        }
    }, [selectedPath, setSearchParams]);

    useEffect(() => {
        async function loadQuizTemplates() {
            const {data, error} = await supabase
                .from("user_quiz_stats_view")
                .select(`
                    id,
                    title,
                    description,
                    deck_name,
                    item_count,
                    attempt_count,
                    last_attempt_at,
                    last_score
                `);

            if (error) {
                console.error("Error loading user_quiz_stats_view:", error);
                return;
            }
            setQuizTemplates((data || []) as QuizTemplate[]);
        }

        loadQuizTemplates();
    }, []);

    useEffect(() => {
        async function loadFolderStats() {
            setLoading(true);
            const {data, error} = await supabase
                .from("user_deck_stats_view")
                .select("deck_id, deck_name, item_count, learned_count, due_count, ease_sum, recent_unlearned_count")
                .order("deck_name", {ascending: true});

            if (error) {
                console.error("Error loading user_deck_stats_view:", error);
            } else if (data) {
                setDeckStats(data as DeckStat[]);
            }
            setLoading(false);
        }

        loadFolderStats();
    }, []);

    const { root: tree, deckNameSet } = useMemo(() => buildDeckTree(deckStats), [deckStats]);
    useEffect(() => {
        if (setNavDueCount) {
            setNavDueCount(tree.dueCount ?? 0);
        }
        if (setNavRecentNewCount) {
            setNavRecentNewCount(tree.recentUnlearnedCount ?? 0);
        }
    }, [tree.dueCount, tree.recentUnlearnedCount, setNavDueCount, setNavRecentNewCount]);
    const currentNode = useMemo(() => findNodeByPath(tree, selectedPath), [tree, selectedPath]);

    const childNodes = useMemo(() => currentNode.children
        .slice()
        .sort((a, b) => {
            const na = parseLeadingNumber(a.name);
            const nb = parseLeadingNumber(b.name);

            if (na != null && nb != null && na !== nb) return na - nb;
            if (na != null && nb == null) return -1;
            if (na == null && nb != null) return 1;
            return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
        }), [currentNode]);
    const quizzesInCurrentDir = useMemo(
        () =>
            quizTemplates
                .filter((t) => {
                    const path = t.deck_name ?? "";
                    if (!selectedPath) {
                        return !deckNameSet.has(path);
                    }
                    return path === selectedPath;
                })
                .map((t) => ({
                    id: t.id,
                    title: t.title,
                    deckPath: t.deck_name ?? "",
                    description: t.description ?? "",
                    itemCount: t.item_count ?? "",
                    attemptCount: t.attempt_count ?? 0,
                    lastScore: t.last_score ?? 0,
                    lastAttemptAt: t.last_attempt_at ?? 0,
                })),
        [quizTemplates, selectedPath, deckNameSet]
    );

    const breadcrumbSegments = selectedPath ? selectedPath.split("/").filter(Boolean).map((seg, idx, arr) => ({
        name: seg, fullPath: arr.slice(0, idx + 1).join("/"),
    })) : [];

    // 根目录 + 面包屑，全部用“带图标按钮”的形式呈现
    const breadcrumbButtons = [{name: "全部知识", fullPath: ""}, ...breadcrumbSegments,];

    return (<div className="mt-8 w-fit max-w-5xl mx-auto space-y-6">
        {/* 顶部：当前目录 + 面包屑按钮 */}
        <div>
            <div className="mt-4 flex items-center justify-between w-full">
                {/* 左边：当前目录 / 面包屑按钮 */}
                <div className="flex items-center flex-wrap gap-3">
                    {breadcrumbButtons.map((seg) => {
                        //const isActive = selectedPath === seg.fullPath;
                        const node = findNodeByPath(tree, seg.fullPath);
                        const isDeck = node?.isDeck ?? false;

                        return (
                            <Button variant="outline"
                                    key={seg.fullPath || "__root__"}
                                    type="button"
                                    onClick={() => setSelectedPath(seg.fullPath)}
                                    className="px-4 py-2.5 text-xl gap-1"

                            >
                                {isDeck ? (
                                    <Layers size={28} className="text-amber-300"/>
                                ) : (
                                    <Folder size={28} className="text-slate-300"/>
                                )}
                                <span>{seg.name}</span>
                            </Button>
                        );
                    })}
                </div>

                {/* 右边：查看 / 学习（与目录节点对齐） */}
                <div className="flex items-center gap-4 shrink-0 ml-6">

                    {/* 学习：同字号，与目录节点对齐 */}
                    <Button
                        variant="primary"
                        disabled={!selectedPath}
                        className="w-40 px-5 py-3 text-xl font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                        onClick={() => {
                            navigate(`/decks/${encodeURIComponent(selectedPath)}/practice`);
                        }
                        }
                    >
                        学习
                    </Button>
                </div>
            </div>
        </div>

        {/* 下方两列 */}
        <div className="grid grid-cols-1 md:grid-cols-[4fr_3fr] gap-6 items-start">
            <div className="flex flex-col gap-3">
                {currentNode?.isDeck && currentNode.deckId && (
                    <DeckStatus deckId={currentNode.deckId}/>
                )}

                {/* 左侧：子目录 */}
                <section
                    className="rounded-2xl border border-slate-200 bg-white/80 p-4 shadow-sm dark:border-slate-700/70 dark:bg-slate-900/60">

                    {loading ? (
                        <div className="text-xs text-muted">正在载入目录统计…</div>) : childNodes.length === 0 ? (
                        <div className="text-xs text-muted">这个目录下没有子目录。</div>) : (
                        <div className="flex flex-col gap-2">
                            {childNodes.map((node) => (
                                <div
                                    key={node.fullPath}
                                    className="flex flex-col gap-1 rounded-xl border border-slate-200 bg-white text-slate-900 shadow-sm dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-100"
                                >
                                    <button
                                        onClick={() => setSelectedPath(node.fullPath)}
                                        className="flex items-center justify-start px-3 py-2 rounded-xl hover:bg-slate-100 hover:border-slate-300 transition-colors dark:hover:bg-slate-800/70"
                                    >
                                        <div className="w-10">
                                            {node.isDeck ? (
                                                <Layers size={24} className="text-amber-500"/>     // ⭐ deck 图标
                                            ) : (
                                                <Folder size={24} className="text-slate-500"/>   // ⭐ 目录图标
                                            )}
                                        </div>
                                        <div className="w-full">
                                            <div className="grid grid-cols-[2fr_2fr_1fr] items-center gap-2 w-full">

                                                {/* 名称 + 统计信息 同一行 */}
                                                <span className="text-sm  text-left">{node.name}</span>
                                                <span
                                                    className="ml-2 text-[11px] text-slate-500 dark:text-slate-400">{node.deckCount ?? 0} decks · {node.totalItems ?? 0} cards</span>
                                                <span>{calcProgress(node)}%</span>
                                            </div>
                                            <div
                                                className="ml-0 mr-3 mb-2 h-[2px] rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                                                <div
                                                    className="h-full bg-blue-800 dark:bg-blue-700 transition-all"
                                                    style={{width: `${Math.min(100, Math.max(0, calcProgress(node)))}%`}}
                                                />
                                            </div>
                                        </div>
                                    </button>

                                </div>
                            ))}
                        </div>)}
                </section>
            </div>

            {/* 右侧：测验列表 + 新增按钮 */}
            <div className="flex flex-col gap-3">
                <section
                    className="rounded-2xl border border-blue-200 bg-blue-50/70 backdrop-blur-md p-4 shadow-sm dark:border-blue-600/80 dark:bg-blue-900/40">
                    <h2 className="text-sm font-medium text-slate-900 mb-3 dark:text-slate-100"/>
                    {quizzesInCurrentDir.length === 0 ? (<div className="text-xs text-muted">
                        暂无测验。
                    </div>) : (<div className="space-y-3">
                        {quizzesInCurrentDir.map((quiz) => (<div
                            key={quiz.id}
                            className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm hover:border-slate-300 hover:bg-slate-50 transition-colors dark:border-slate-700 dark:bg-slate-900/80 dark:hover:bg-slate-800/70"
                        >
                            <div>
                                <div className="text-sm font-medium text-slate-900 dark:text-slate-100">
                                    {quiz.title}
                                </div>
                                <div className="text-[10px] text-slate-500 dark:text-slate-400">
                                    {quiz.itemCount} 道题, 已练习{quiz.attemptCount}次，最后得分{quiz.lastScore}
                                </div>
                            </div>

                            <div className="flex items-center gap-2">
                                <Button
                                    variant="ghostSecond"
                                    className="w-20 text-sm"
                                    onClick={() => navigate(`/quiz-runs/${quiz.id}`)}
                                >
                                    查看
                                </Button>
                                <Button
                                    variant="outline"
                                    className="w-20 text-sm"
                                    onClick={() => navigate(`/quizzes/${quiz.id}/take`)}
                                >
                                    开始
                                </Button>
                            </div>
                        </div>))}
                    </div>)}
                </section>
                <div className="flex justify-between gap-2">
                    <Button
                        variant="ghost"
                        className="text-sm flex items-center gap-1"
                        onClick={() => navigate(`/decks/new?path=${encodeURIComponent(selectedPath)}`)}
                        title="新建知识卡片组"
                    >
                        <Layers size={16} />
                        <span>新建卡组</span>
                    </Button>
                    <Button
                        variant="none"
                        className="text-sm border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 hover:border-blue-300 rounded-lg px-3 py-2 flex items-center gap-1 dark:border-blue-600 dark:bg-blue-900/40 dark:text-blue-100 dark:hover:bg-blue-800/60"
                        onClick={() => {
                            const params = new URLSearchParams();
                            params.set("path", selectedPath);
                            if (currentNode?.isDeck) params.set("is_deck", "1");
                            navigate(`/quizzes/new?${params.toString()}`);
                        }}
                    >
                        <PencilLine size={16} />
                        <span>新增测验</span>
                    </Button>
                </div>
            </div>
        </div>
    </div>);
}
