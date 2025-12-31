import {useEffect, useState, useMemo} from "react";
import {useParams, useNavigate} from "react-router-dom";
import {BookOpen, Trophy, Trash2, Check, CornerUpLeft, PencilLine} from "lucide-react";
import {supabase} from "../../lib/supabaseClient";
import {Button} from "../components/ui/Button";
import { useRef } from "react";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { parseFront } from "../../lib/quizFormat";

type QuizRunRecord = {
    id: string;
    template_id: string | null;
    score: number | null;
    total_items: number | null;
    correct_items: number | null;
    started_at: string | null;
    finished_at: string | null;
    template?: {
        id: string;
        title: string;
        description: string | null;
    } | null;
};

type TemplateStats = {
    id: string;
    title: string;
    description: string | null;
    deck_name: string;
    attempt_count: number;
    last_score: number | null;
};

type UserRunSummary = {
    id: string;
    template_id: string | null;
    started_at: string | null;
    finished_at: string | null;
    score: number | null;
    config: Record<string, unknown> | null;
};

type RecentAttempt = {
    answer: string;
    isCorrect: boolean;
};

type QuestionRow = {
    cardId: string;
    position: number;
    promptSummary: string;
    promptFull: string;
    recentAttempts: RecentAttempt[];
    accuracy: number | null;
    inWrongBook: boolean;
};

type QuizItemsPayload = {
    items?: Array<{ card_id?: string; position?: number }>;
};

function truncateText(text: string, maxChars: number): string {
    const trimmed = text.trim();
    if (trimmed.length <= maxChars) return trimmed;
    return `${trimmed.slice(0, maxChars)}…`;
}

function buildPromptFull(frontRaw: string): string {
    const parsed = parseFront(frontRaw);
    const prompt = parsed.prompt?.trim() || frontRaw.trim();
    const options = Array.isArray(parsed.options) ? parsed.options : [];
    if (!options.length) return prompt;
    const formatted = options
        .map((opt, idx) => ` ${opt}`)
        .join(" ");
    return `${prompt} 选项: ${formatted}`;
}

function formatUserAnswer(raw: string | null): string {
    if (!raw) return "";
    try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) return parsed.join(" / ");
        if (typeof parsed === "string") return parsed;
        return String(parsed);
    } catch {
        return raw;
    }
}

export default function QuizResultPage() {
    const navigate = useNavigate();
    const {quizId, runId} = useParams<{ quizId?: string; runId?: string }>();
    const [result, setResult] = useState<QuizRunRecord | null>(null);
    const [templateStats, setTemplateStats] = useState<TemplateStats | null>();
    const [userRuns, setUserRuns] = useState<UserRunSummary[]>([]);
    const [loading, setLoading] = useState(true);
    const [runsLoading, setRunsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [runMessage, setRunMessage] = useState<string | null>(null);
    const [deleting, setDeleting] = useState(false);
    const [editingTitle, setEditingTitle] = useState(false);
    const [titleInput, setTitleInput] = useState("");
    const [savingTitle, setSavingTitle] = useState(false);
    const titleEditRef = useRef<HTMLDivElement | null>(null);
    const [editingDesc, setEditingDesc] = useState(false);
    const [descInput, setDescInput] = useState("");
    const [savingDesc, setSavingDesc] = useState(false);
    const descEditRef = useRef<HTMLDivElement | null>(null);
    const [editingDeckName, setEditingDeckName] = useState(false);
    const [deckNameInput, setDeckNameInput] = useState("");
    const [savingDeckName, setSavingDeckName] = useState(false);
    const deckNameEditRef = useRef<HTMLDivElement | null>(null);
    const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
    const [questionRows, setQuestionRows] = useState<QuestionRow[]>([]);
    const [questionsLoading, setQuestionsLoading] = useState(false);
    const [questionsError, setQuestionsError] = useState<string | null>(null);
    const [showAllAccuracy, setShowAllAccuracy] = useState(false);

    useEffect(() => {
        async function load() {
            if (!quizId && !runId) {
                setError("缺少必要参数：需要提供测验模板 ID。");
                setLoading(false);
                return;
            }
            setLoading(true);
            setError(null);
            setRunMessage(null);

            const templatePromise = quizId
                ? supabase
                    .from("user_quiz_stats_view")
                    .select("id, title, description, deck_name, attempt_count, last_score")
                    .eq("id", quizId)
                    .maybeSingle()
                : Promise.resolve({data: null, error: null});

            const runPromise = runId
                ? supabase
                    .from("quiz_runs")
                    .select("id, template_id, score, total_items, correct_items, started_at, finished_at, template:quizzes(id, title, description)")
                    .eq("id", runId)
                    .maybeSingle()
                : Promise.resolve({data: null, error: null});

            const [{data: tmpl, error: tmplErr}, {data: run, error: runErr}] = await Promise.all([
                templatePromise,
                runPromise,
            ]);

            if ((quizId && (tmplErr || !tmpl))) {
                setError("未找到对应的测验模板。");
                setLoading(false);
                return;
            }

            if (runErr) {
                console.error("加载测验结果失败", runErr);
            }
            if (tmpl) {
                setTemplateStats(tmpl as TemplateStats);
            }
            if (run) {
                const tplRaw = (run as any)?.template;
                const templateNormalized = Array.isArray(tplRaw) ? tplRaw[0] : tplRaw;
                setResult({
                    ...run,
                    template: templateNormalized,
                } as QuizRunRecord);
            } else if (runId) {
                setRunMessage("未找到对应的测验记录。");
                setResult(null);
            } else {
                setResult(null);
            }

            const targetTemplateId = quizId ?? (run as any)?.template_id ?? null;
            if (targetTemplateId) {
                setRunsLoading(true);
                const {data: runsData, error: runsErr} = await supabase
                    .from("user_quiz_runs_view")
                    .select("id, template_id, started_at, finished_at, score, config")
                    .eq("template_id", targetTemplateId)
                    .order("finished_at", {ascending: false});

                if (!runsErr && runsData) {
                    setUserRuns(runsData as UserRunSummary[]);
                }
                setRunsLoading(false);
            }

            setLoading(false);
        }

        void load();
    }, [quizId, runId]);

    useEffect(() => {
        const templateId =
            templateStats?.id ??
            result?.template?.id ??
            result?.template_id ??
            quizId ??
            null;
        if (!templateId) return;
        let isActive = true;

        async function loadQuestionRows() {
            setQuestionsLoading(true);
            setQuestionsError(null);

            const { data: quizData, error: quizErr } = await supabase
                .from("user_active_quizzes")
                .select("items")
                .eq("id", templateId)
                .maybeSingle();

            if (!isActive) return;
            if (quizErr || !quizData) {
                setQuestionsError("加载题目明细失败");
                setQuestionsLoading(false);
                return;
            }

            const rawItems = (quizData as { items?: QuizItemsPayload }).items?.items ?? [];
            const items = rawItems
                .filter((item) => item?.card_id)
                .map((item) => ({
                    cardId: item.card_id as string,
                    position: typeof item.position === "number" ? item.position : 0,
                }))
                .sort((a, b) => a.position - b.position);

            if (!items.length) {
                setQuestionRows([]);
                setQuestionsLoading(false);
                return;
            }

            const cardIds = items.map((item) => item.cardId);
            const [cardsRes, reviewsRes, statsRes, wrongDeckRes] = await Promise.all([
                supabase
                    .from("cards")
                    .select("id, front")
                    .in("id", cardIds),
                supabase
                    .from("card_reviews")
                    .select("card_id, user_answer, is_correct, reviewed_at")
                    .in("card_id", cardIds)
                    .eq("is_question", true)
                    .order("reviewed_at", { ascending: false }),
                supabase
                    .from("card_stats")
                    .select("card_id, correct_count, review_count")
                    .in("card_id", cardIds),
                supabase
                    .from("decks")
                    .select("items")
                    .eq("title", `${deckPath}/_错题本`)
                    .maybeSingle(),
            ]);

            if (!isActive) return;
            if (cardsRes.error || reviewsRes.error || statsRes.error || wrongDeckRes.error) {
                console.error("load question rows error", {
                    cardsErr: cardsRes.error,
                    reviewsErr: reviewsRes.error,
                    statsErr: statsRes.error,
                    wrongDeckErr: wrongDeckRes.error,
                });
                setQuestionsError("加载题目明细失败");
                setQuestionsLoading(false);
                return;
            }

            const cardMap = new Map<string, string>();
            for (const card of cardsRes.data ?? []) {
                cardMap.set(card.id, card.front ?? "");
            }

            const statsMap = new Map<string, { correct: number; total: number }>();
            for (const stat of statsRes.data ?? []) {
                const total = Number(stat.review_count ?? 0);
                const correct = Number(stat.correct_count ?? 0);
                statsMap.set(stat.card_id, { correct, total });
            }

            const reviewMap = new Map<string, RecentAttempt[]>();
            for (const review of reviewsRes.data ?? []) {
                const list = reviewMap.get(review.card_id) ?? [];
                if (list.length >= 3) continue;
                    list.push({
                        answer: formatUserAnswer(review.user_answer ?? ""),
                        isCorrect: Boolean(review.is_correct),
                    });
                reviewMap.set(review.card_id, list);
            }

            const wrongItems = (wrongDeckRes.data as { items?: { items?: Array<{ card_id?: string }> } } | null)
                ?.items?.items ?? [];
            const wrongSet = new Set(
                wrongItems
                    .map((item) => item?.card_id)
                    .filter((id): id is string => Boolean(id))
            );

            const rows: QuestionRow[] = items.map((item) => {
                const frontRaw = cardMap.get(item.cardId) ?? "";
                const promptFull = buildPromptFull(frontRaw);
                const stats = statsMap.get(item.cardId);
                const accuracy =
                    stats && stats.total > 0
                        ? Math.round((stats.correct / stats.total) * 100)
                        : null;
                return {
                    cardId: item.cardId,
                    position: item.position,
                    promptFull,
                    promptSummary: truncateText(promptFull, 24),
                    recentAttempts: reviewMap.get(item.cardId) ?? [],
                    accuracy,
                    inWrongBook: wrongSet.has(item.cardId),
                };
            });

            setQuestionRows(rows);
            setQuestionsLoading(false);
        }

        void loadQuestionRows();
        return () => {
            isActive = false;
        };
    }, [templateStats?.id, result?.template?.id, result?.template_id, quizId]);

    // 点击外部取消标题编辑
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

    // 点击外部取消 deck 路径编辑
    useEffect(() => {
        if (!editingDeckName) return;
        const handleClickOutside = (e: MouseEvent) => {
            if (!deckNameEditRef.current) return;
            if (!deckNameEditRef.current.contains(e.target as Node)) {
                setEditingDeckName(false);
            }
        };
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, [editingDeckName]);

    const title = templateStats?.title;
    const descriptionText = templateStats?.description ?? result?.template?.description ?? null;
    const correct = result?.correct_items ?? 0;
    const total = result?.total_items ?? 0;
    const percent = total > 0 ? Math.round((correct / total) * 100) : 0;
    const deckPath = templateStats?.deck_name ?? "";
    const hasRun = Boolean(runId && result);
    const hasHistory = userRuns.length > 0;
    const avgScore = useMemo(() => {
        if (!userRuns.length) return null;
        const valid = userRuns.filter((r) => typeof r.score === "number");
        if (!valid.length) return null;
        const sum = valid.reduce((acc, r) => acc + ((r.score ?? 0) as number), 0);
        return sum / valid.length;
    }, [userRuns]);
    const filteredQuestionRows = showAllAccuracy
        ? questionRows
        : questionRows.filter((row) => row.accuracy === null || row.accuracy < 100);

    async function handleDeleteTemplate() {
        if (!quizId && !templateStats?.id) return;
        const targetId = quizId ?? templateStats?.id;
        if (!targetId) return;
        setDeleting(true);
        setShowDeleteConfirm(false);
        const {error: delErr} = await supabase
            .from("quizzes")
            .update({ is_deleted: true })
            .eq("id", targetId);
        setDeleting(false);
        if (delErr) {
            alert("删除失败，请稍后再试");
            console.error("delete template error", delErr);
            return;
        }
        navigate(`/quizzes?path=${templateStats?.deck_name ?? ""}`);
        //window.location.href = "/quizzes";
    }

    async function handleSaveDeckName() {
        const targetId = templateStats?.id ?? quizId;
        if (!targetId) return;
        const next = deckNameInput.trim();
        setSavingDeckName(true);
        const { error: updErr } = await supabase
            .from("quizzes")
            .update({ deck_name: next })
            .eq("id", targetId);
        setSavingDeckName(false);
        if (updErr) {
            alert("更新路径失败，请稍后再试");
            return;
        }
        setTemplateStats((prev) => (prev ? { ...prev, deck_name: next } : prev));
        setEditingDeckName(false);
    }

    async function saveTitle() {
        if (!titleInput.trim()) return;
        const targetId = templateStats?.id ?? quizId ?? result?.template?.id;
        if (!targetId) return;
        setSavingTitle(true);
        const { error: updErr } = await supabase
            .from("quizzes")
            .update({ title: titleInput.trim() })
            .eq("id", targetId);
        setSavingTitle(false);
        if (updErr) {
            alert("更新标题失败，请稍后再试");
            return;
        }
        setTemplateStats((prev) =>
            prev ? { ...prev, title: titleInput.trim() } : prev
        );
        setResult((prev) =>
            prev
                ? {
                    ...prev,
                    template: prev.template
                        ? { ...prev.template, title: titleInput.trim() }
                        : prev.template,
                }
                : prev
        );
        setEditingTitle(false);
    }

    async function saveDescription() {
        const targetId = templateStats?.id ?? quizId ?? result?.template?.id;
        if (!targetId) return;
        setSavingDesc(true);
        const { error: updErr } = await supabase
            .from("quizzes")
            .update({ description: descInput })
            .eq("id", targetId);
        setSavingDesc(false);
        if (updErr) {
            alert("更新描述失败，请稍后再试");
            return;
        }
        setTemplateStats((prev) =>
            prev ? { ...prev, description: descInput } : prev
        );
        setResult((prev) =>
            prev
                ? {
                    ...prev,
                    template: prev.template
                        ? { ...prev.template, description: descInput }
                        : prev.template,
                }
                : prev
        );
        setEditingDesc(false);
    }

    function handleDeckNameKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
        if (e.key === "Enter") {
            e.preventDefault();
            void handleSaveDeckName();
        }
        if (e.key === "Escape") {
            e.preventDefault();
            setEditingDeckName(false);
        }
    }

    if (loading) {
        return (
            <div className="flex flex-col items-center justify-center py-12 text-slate-700 dark:text-slate-300">
                正在加载测验结果…
            </div>
        );
    }

    if (error) {
        return (
            <div
                className="flex flex-col items-center justify-center gap-4 py-12 px-4 text-slate-700 dark:text-slate-300">
                <div className="text-sm">{error}</div>
                <Button variant="outline" onClick={() => (window.location.href = "/quizzes")}>
                    返回测验列表
                </Button>
            </div>
        );
    }

    return (
        <div className="max-w-3xl mx-auto py-10 px-4 text-slate-900 dark:text-slate-100 space-y-6">
            {/* 标题和描述 */}
            <div className="flex items-center gap-3 mb-4">
                <BookOpen className="w-10 h-10 text-emerald-600 dark:text-emerald-400" />
                <div className="flex-1">
                    <div className="text-xl font-semibold text-slate-900 dark:text-white">
                        {!editingTitle && (
                            <button
                                type="button"
                                className="text-left w-full"
                                onDoubleClick={() => {
                                    if (templateStats?.id || quizId || result?.template?.id) {
                                        setTitleInput(title ?? "");
                                        setEditingTitle(true);
                                    }
                                }}
                                title="双击编辑标题"
                            >
                                {title}
                            </button>
                        )}
                        {editingTitle && (
                            <div
                                className="flex items-center gap-2"
                                ref={titleEditRef}
                            >
                                <input
                                    className="flex-1 rounded-lg border border-slate-300 px-3 py-1 text-xl font-semibold text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                                    value={titleInput}
                                    onChange={(e) => setTitleInput(e.target.value)}
                                    autoFocus
                                    onKeyDown={(e) => {
                                        if (e.key === "Enter") {
                                            e.preventDefault();
                                            void saveTitle();
                                        }
                                        if (e.key === "Escape") {
                                            e.preventDefault();
                                            setEditingTitle(false);
                                        }
                                    }}
                                />
                                <Button
                                    variant="primary"
                                    className="px-4 py-1 text-sm whitespace-nowrap"
                                    disabled={savingTitle || !titleInput.trim()}
                                    onClick={() => void saveTitle()}
                                >
                                    {savingTitle ? "保存中…" : <Check className="w-4 h-4" />}
                                </Button>
                            </div>
                        )}
                    </div>
                    <div className="text-xs text-slate-600 dark:text-slate-400 mt-1">
                        {!editingDesc && (
                            <button
                                type="button"
                                className="text-left w-full"
                                onDoubleClick={() => {
                                    if (templateStats?.id || quizId || result?.template?.id) {
                                        setDescInput(descriptionText ?? "");
                                        setEditingDesc(true);
                                    }
                                }}
                                title="双击编辑描述"
                            >
                                {descriptionText?.trim()
                                    ? descriptionText
                                    : <span className="text-slate-400 dark:text-slate-500">[双击添加测验说明]</span>}
                            </button>
                        )}
                        {editingDesc && (
                            <div className="flex items-center gap-2" ref={descEditRef}>
                                <input
                                    className="flex-1 rounded-lg border border-slate-300 px-3 py-1 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                                    value={descInput}
                                    onChange={(e) => setDescInput(e.target.value)}
                                    autoFocus
                                    onKeyDown={(e) => {
                                        if (e.key === "Enter") {
                                            e.preventDefault();
                                            void saveDescription();
                                        }
                                        if (e.key === "Escape") {
                                            e.preventDefault();
                                            setEditingDesc(false);
                                        }
                                    }}
                                />
                                <Button
                                    variant="primary"
                                    className="px-3 py-1 text-xs"
                                    disabled={savingDesc}
                                    onClick={() => void saveDescription()}
                                >
                                    {savingDesc ? "保存中…" : <Check className="w-4 h-4" />}
                                </Button>
                            </div>
                        )}
                    </div>
                </div>
                <div className="flex-1 flex items-center justify-end gap-3">
                    {templateStats && (
                        <Button
                            variant="iconWarning"
                            disabled={deleting}
                            onClick={() => setShowDeleteConfirm(true)}
                            title="删除测验"
                        >
                            {deleting ? "删除中…" : <Trash2 className="w-5 h-5" />}
                        </Button>
                    )}
                    {editingDeckName ? (
                        <div ref={deckNameEditRef} className="flex items-center gap-2">
                            <input
                                autoFocus
                                value={deckNameInput}
                                onChange={(e) => setDeckNameInput(e.target.value)}
                                onKeyDown={handleDeckNameKeyDown}
                                className="w-52 rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 shadow-sm focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 dark:bg-slate-800 dark:border-slate-600 dark:text-slate-100 dark:focus:border-emerald-400 dark:focus:ring-emerald-400"
                                placeholder="输入路径，回车保存"
                            />
                            {savingDeckName && (
                                <span className="text-xs text-slate-500 dark:text-slate-300">保存中…</span>
                            )}
                        </div>
                    ) : (
                        <button
                            type="button"
                            className="text-sm text-slate-500 hover:text-slate-700 dark:text-slate-300 dark:hover:text-slate-100"
                            onDoubleClick={() => {
                                setDeckNameInput(deckPath);
                                setEditingDeckName(true);
                            }}
                            title="双击编辑所属路径（回车保存）"
                        >
                            {deckPath?.trim()
                                ? deckPath
                                : <span className="text-slate-400 dark:text-slate-500">[双击设置路径]</span>}
                        </button>
                    )}
                    {templateStats?.id && (
                        <Button
                            variant="iconRound"
                            className="text-emerald-600 hover:text-white hover:bg-emerald-600 dark:text-emerald-300 dark:hover:text-emerald-100 dark:hover:bg-emerald-700"
                            onClick={() => navigate(`/quizzes/${templateStats.id}/take`)}
                            title="做测验"
                        >
                            <PencilLine className="w-5 h-5" />
                        </Button>
                    )}
                    <Button
                        variant="iconRound"
                        className="text-emerald-600 hover:text-white hover:bg-emerald-600 dark:text-emerald-300 dark:hover:text-emerald-100 dark:hover:bg-emerald-700"
                        onClick={() => navigate(`/quizzes?path=${deckPath}`)}
                        title="返回测验列表"
                    >
                        <CornerUpLeft className="w-6 h-6" />
                        <span className="sr-only">返回测验列表</span>
                    </Button>
                </div>
            </div>

            {/* 上半：本次测验结果（可为空或报错） */}
            {hasRun && (
                <div
                    className="rounded-2xl border border-slate-200 bg-white p-6 text-slate-900 shadow-sm dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-100">

                    <div className="flex items-start gap-3">
                        <div
                            className="w-12 h-12 rounded-xl bg-emerald-100 text-emerald-700 flex items-center justify-center text-xl font-semibold dark:bg-emerald-900/40 dark:text-emerald-200">
                            <Trophy className="w-6 h-6"/>
                        </div>
                        <div className="flex-1 space-y-3">
                            <div className="text-lg">
                                正确题数：
                                <span className="font-semibold text-emerald-700 dark:text-emerald-400">
                                {correct}
                                </span>
                                <span className="text-slate-600 dark:text-slate-400"> / {total}</span>
                            </div>
                            <div className="text-sm text-slate-700 dark:text-slate-300">
                                正确率{" "}
                                <span className="font-semibold text-emerald-700 dark:text-sky-400">
                                  {percent}%
                                </span>
                            </div>
                            <div className="text-xs text-slate-500 dark:text-slate-400">
                                {result?.started_at && <span className="mr-4">开始：{result.started_at}</span>}
                                {result?.finished_at && <span>结束：{result.finished_at}</span>}
                            </div>
                        </div>
                        <div className="flex flex-wrap mt-5 justify-end">

                            {result?.template_id && (
                                <Button variant="primary"
                                        onClick={() => navigate(`/quizzes/${result.template_id}/take`)}
                                >
                                    再做一次
                                </Button>
                            )}
                        </div>
                    </div>


                </div>
            )}

            {!hasRun && runMessage && (
                <div
                    className="rounded-2xl border border-dashed border-slate-300 bg-white/70 p-4 text-xs text-slate-600 shadow-sm dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-300">
                    {runMessage}
                </div>
            )}

            {/* 下半：模板统计 */}
            <div
                className="rounded-2xl border border-slate-200 bg-white/70 p-6 text-slate-800 shadow-sm dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200">

                {templateStats ? (
                    <div className="space-y-2 text-base">
                        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-700 dark:text-slate-300">
                            <div className="flex flex-wrap items-center gap-3">
                                <span>测验次数：{templateStats.attempt_count ?? 0}</span>
                                {typeof templateStats.last_score === "number" && (
                                    <span>最后成绩：{Math.round((templateStats.last_score ?? 0) * 100)}%</span>
                                )}
                                {typeof avgScore === "number" && (
                                    <span>平均成绩：{Math.round(avgScore * 100)}%</span>
                                )}
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                        {runMessage ?? "暂无统计信息。"}
                    </div>
                )}

                <div className="mt-6">
                    {questionsLoading && (
                        <div className="text-xs text-slate-500 dark:text-slate-400">加载题目明细中…</div>
                    )}
                    {questionsError && (
                        <div className="text-xs text-rose-600 dark:text-rose-400">{questionsError}</div>
                    )}
                    {!questionsLoading && !questionsError && questionRows.length === 0 && (
                        <div className="text-xs text-slate-500 dark:text-slate-400">暂无题目明细。</div>
                    )}
                    {!questionsLoading && !questionsError && questionRows.length > 0 && (
                        <div>
                            <table className="w-full text-sm table-auto">
                                <thead className="text-sm text-slate-500 dark:text-slate-400">
                                    <tr className="border-b border-slate-200 dark:border-slate-700">
                                        <th className="py-2 text-left font-medium w-10">#</th>
                                        <th className="py-2 text-left font-medium">题目</th>
                                        {[1, 2, 3].map((idx) => (
                                            <th key={idx} className="py-2 text-left font-medium w-20">{`最近${idx}`}</th>
                                        ))}
                                        <th className="py-2 text-left font-medium w-14">
                                            <div className="flex items-center gap-2">
                                                <input
                                                    type="checkbox"
                                                    checked={showAllAccuracy}
                                                    onChange={(e) => setShowAllAccuracy(e.target.checked)}
                                                    title="显示正确率 100% 的题目"
                                                /><span>%</span>
                                            </div>
                                        </th>
                                        <th className="py-2 text-center font-medium w-14">错题本</th>
                                    </tr>
                                </thead>
                                <tbody className="text-slate-700 dark:text-slate-300">
                                    {filteredQuestionRows.map((row, rowIndex) => (
                                        <tr key={row.cardId} className="border-b border-slate-100 dark:border-slate-800">
                                            <td className="py-2 text-slate-500 dark:text-slate-400">
                                                {row.position || rowIndex + 1}
                                            </td>
                                            <td className="py-2 pr-3 whitespace-nowrap max-w-[320px]">
                                                <span title={row.promptFull} className="block truncate">
                                                    {row.promptSummary || "—"}
                                            </span>
                                        </td>
                                            {[0, 1, 2].map((idx) => {
                                                const attempt = row.recentAttempts[idx];
                                                if (!attempt) {
                                                    return (
                                                        <td key={idx} className="py-2 text-slate-400">
                                                            —
                                                        </td>
                                                    );
                                                }
                                                const answerSummary = truncateText(attempt.answer || "—", 12);
                                                return (
                                                    <td key={idx} className="py-2">
                                                        <div
                                                            className={attempt.isCorrect
                                                                ? "text-emerald-800 dark:text-emerald-200"
                                                                : "text-rose-900 dark:text-rose-50 bg-rose-200 dark:bg-rose-900/70 px-2 py-0.5 rounded"}
                                                            title={attempt.answer}
                                                        >
                                                            {answerSummary}
                                                        </div>
                                                    </td>
                                                );
                                            })}
                                            <td className="py-2">
                                                {typeof row.accuracy === "number" ? `${row.accuracy}%` : "—"}
                                            </td>
                                            <td className="py-2 text-center">
                                                {row.inWrongBook ? "✓" : ""}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>

            <ConfirmDialog
                open={showDeleteConfirm}
                title="删除测验模板"
                description="确认删除该测验模板？此操作不可恢复。"
                confirmLabel="确认删除"
                cancelLabel="取消"
                loading={deleting}
                onConfirm={handleDeleteTemplate}
                onCancel={() => !deleting && setShowDeleteConfirm(false)}
            />

            {/* 历史测验记录 */}
            <div
                className="rounded-2xl border border-slate-200 bg-white/80 p-6 text-slate-800 shadow-sm dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200">
                <div className="text-sm font-semibold mb-3 text-slate-900 dark:text-slate-100">历史测验记录</div>
                {runsLoading && (
                    <div className="text-xs text-slate-500 dark:text-slate-400">加载历史记录中…</div>
                )}
                {!runsLoading && hasHistory ? (
                    <div className="space-y-2 text-xs text-slate-700 dark:text-slate-300">
                        {userRuns.map((r) => (
                            <div
                                key={r.id}
                                className="rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900/50"
                            >
                                <div className="flex flex-col">
                                    <span className="font-medium">
                                        得分：{typeof r.score === "number"
                                        ? Math.round((r.score ?? 0) * 100) + "%"
                                        : "-"}
                                    </span>
                                    <span className="text-slate-500 dark:text-slate-400">开始：{r.started_at ?? "-"}</span>
                                    <span className="text-slate-500 dark:text-slate-400">结束：{r.finished_at ?? "-"}</span>
                                </div>
                            </div>
                        ))}
                    </div>
                ) : !runsLoading ? (
                    <div className="text-xs text-slate-500 dark:text-slate-400">暂无历史记录。</div>
                ) : null}
            </div>
        </div>
    );
}
