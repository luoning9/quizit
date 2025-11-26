import {useEffect, useMemo, useState} from "react";
import {supabase} from "../../lib/supabaseClient";
import {Button} from "../components/ui/Button";
import {Folder, Layers} from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

/**
 * 来自 view：deck_folder_stats 的记录
 * path            目录路径，如 "A", "A/B", "Physics/Grade8"
 * deck_count      该节点下（含子节点）的 deck 数量
 * total_items     该节点下（含子节点）的 items 总数
 * total_ease_factor 该节点下所有已学习卡片的 ease_factor 之和
 */
interface FolderStats {
    path: string;
    deck_count: number;
    total_items: number;
    total_ease_factor: number;
    //is_deck: boolean;
    deck_id: string;
}

interface DeckTreeNode {
    name: string;
    fullPath: string;
    children: DeckTreeNode[];
    deckCount: number;
    totalItems: number;
    totalEaseFactor: number;
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

// 根据 view 的 path 构造目录树
function buildDeckTree(stats: FolderStats[]): DeckTreeNode {
    const root: DeckTreeNode = {
        name: "", fullPath: "", children: [], deckCount: 0, totalItems: 0, totalEaseFactor: 0, isDeck: false, deckId: "",
    };

    const ensureChild = (parent: DeckTreeNode, name: string): DeckTreeNode => {
        const existing = parent.children.find((c) => c.name === name);
        if (existing) return existing;

        const fullPath = parent.fullPath ? `${parent.fullPath}/${name}` : name;

        const node: DeckTreeNode = {
            name, fullPath, children: [], deckCount: 0, totalItems: 0, totalEaseFactor: 0, isDeck: false, deckId: "",
        };

        parent.children.push(node);
        return node;
    };

    for (const row of stats) {
        if (!row.path) continue;
        const parts = row.path.split("/").filter(Boolean);
        if (parts.length === 0) continue;

        let current = root;
        for (const part of parts) {
            current = ensureChild(current, part);
        }

        // 将 view 中的统计挂到对应节点上
        current.deckCount = row.deck_count ?? 0;
        current.totalItems = row.total_items ?? 0;
        current.totalEaseFactor = row.total_ease_factor ?? 0;
        current.deckId = row.deck_id;
        current.isDeck = row.deck_id != null;
    }

    return root;
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

export function MainSelectPage() {
    const [searchParams, setSearchParams] = useSearchParams();
    // 用 URL 里的 ?path=... 作为初始值，没有就用 "/"
    const initialPath = searchParams.get("path") || "";

    const navigate = useNavigate();
    const [folderStats, setFolderStats] = useState<FolderStats[]>([]);
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
                .from("quiz_template_stats")
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
                console.error("Error loading quiz_template_stats:", error);
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
                .from("deck_folder_stats")
                .select("path, deck_count, total_items, total_ease_factor, deck_id")
                .order("path", {ascending: true});

            if (error) {
                console.error("Error loading deck_folder_stats:", error);
            } else if (data) {
                setFolderStats(data as FolderStats[]);
            }
            setLoading(false);
        }

        loadFolderStats();
    }, []);

    const tree = useMemo(() => buildDeckTree(folderStats), [folderStats]);
    const currentNode = useMemo(() => findNodeByPath(tree, selectedPath), [tree, selectedPath]);

    const childNodes = useMemo(() => currentNode.children
        .slice()
        .sort((a, b) => a.name.localeCompare(b.name, "zh-CN")), [currentNode]);

    const quizzesInCurrentDir = useMemo(
        () =>
            quizTemplates
                .filter((t) => (t.deck_name ?? "") === selectedPath)
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
        [quizTemplates, selectedPath]
    );

    const breadcrumbSegments = selectedPath ? selectedPath.split("/").filter(Boolean).map((seg, idx, arr) => ({
        name: seg, fullPath: arr.slice(0, idx + 1).join("/"),
    })) : [];

    // 根目录 + 面包屑，全部用“带图标按钮”的形式呈现
    const breadcrumbButtons = [{name: "全部知识", fullPath: ""}, ...breadcrumbSegments,];

    return (<div className="mt-8 w-fit max-w-5xl mx-auto space-y-6">
        {/* 顶部：当前目录 + 面包屑按钮 */}
        <div>
            <h1 className="text-xl font-semibold">请选择要学习的内容</h1>
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
                                    <Layers size={28} className="text-amber-300" />
                                ) : (
                                    <Folder size={28} className="text-slate-300" />
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
                            navigate(`/decks/${encodeURIComponent(selectedPath)}/practice`);}
                        }
                    >
                        学习
                    </Button>
                    {/* 左侧：查看 + 新增（上下排列） */}
                    <div className="flex flex-col items-start gap-1">
                        {currentNode?.isDeck && (
                            <Button
                                variant="link"
                                className="text-sm px-1 py-0.5 h-auto leading-tight rounded-lg text-blue-300 underline underline-offset-4 hover:text-blue-200"
                                onClick={() => navigate(`/decks/${currentNode.deckId}/edit`)}
                            >
                                Edit Cards
                            </Button>
                        )}

                        <Button
                            variant="link"
                            className="text-sm px-1 py-0.5 h-auto leading-tight rounded-lg text-blue-700 underline underline-offset-4 hover:text-blue-600 dark:text-blue-300 dark:hover:text-blue-200"
                            onClick={() => navigate(`/decks/new?path=${encodeURIComponent(selectedPath)}`)}
                        >
                            New Deck
                        </Button>
                    </div>
                </div>
            </div>
        </div>

        {/* 下方两列 */}
        <div className="grid grid-cols-1 md:grid-cols-[3fr_2fr] gap-6 items-start">
            {/* 左侧：子目录 */}
            <section className="rounded-2xl border border-slate-200 bg-white/80 p-4 shadow-sm dark:border-slate-700/70 dark:bg-slate-900/60">

                {loading ? (
                    <div className="text-xs text-muted">正在载入目录统计…</div>) : childNodes.length === 0 ? (
                    <div className="text-xs text-muted">这个目录下没有子目录。</div>) : (
                    <div className="flex flex-col gap-2">
                        {childNodes.map((node) => (<button
                            key={node.fullPath}
                            onClick={() => setSelectedPath(node.fullPath)}
                            className="flex items-center justify-between px-3 py-2 rounded-xl border border-slate-200 bg-white text-slate-900 hover:bg-slate-100 hover:border-slate-300 transition-colors shadow-sm dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-100 dark:hover:bg-slate-800/70"
                        >
                            <div className="grid grid-cols-[0.6fr_2fr_2fr_2fr] items-center gap-2 w-full">
                                {node.isDeck ? (
                                    <Layers size={18} className="text-amber-500"/>     // ⭐ deck 图标
                                ) : (
                                    <Folder size={18} className="text-slate-500"/>   // ⭐ 目录图标
                                )}
                                {/* 名称 + 统计信息 同一行 */}
                                <span className="text-sm  text-left">{node.name}</span>
                                <span
                                    className="ml-2 text-[11px] text-slate-500 dark:text-slate-400">{node.deckCount ?? 0} decks · {node.totalItems ?? 0} cards</span>
                                <span>{calcProgress(node)}%</span>
                            </div>
                        </button>))}
                    </div>)}
            </section>

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

                            <Button variant="ghost" className="w-20 text-sm"
                                    onClick={() => navigate(`/quizzes/${quiz.id}/take`)}
                            >
                                开始
                            </Button>
                        </div>))}
                    </div>)}
                </section>
                <div className="flex justify-end">
                    <Button
                        variant="outline"
                        className="text-sm"
                        onClick={() => navigate(`/quizzes/new?path=${encodeURIComponent(selectedPath)}`)}
                    >
                        新增测验
                    </Button>
                </div>
            </div>
        </div>
    </div>);
}
