import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { supabase } from "../../lib/supabaseClient";
import { theDeckService } from "../../lib/DeckService";
import { Layers, ArrowLeft, Loader2, RefreshCw, CornerUpLeft } from "lucide-react";
import { Button } from "../components/ui/Button";
import { easeFactorFromLevel, easeFactorToColor, recordDifficultyUpdate } from "../../lib/studyUtils";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { compareDeckTitlesByPath } from "../../lib/deckSort";

type QuestionAnswerPair = {
    card_id: string;
    front: string;
    back: string;
    user_answer: string | null;
};

function truncateText(text: string, maxChars: number): string {
    const trimmed = text.trim();
    if (trimmed.length <= maxChars) return trimmed;
    return `${trimmed.slice(0, maxChars)}…`;
}

function buildPromptFull(frontRaw: string): string {
    const trimmed = frontRaw.trim();
    if (!trimmed) return "";
    try {
        const parsed = JSON.parse(trimmed) as { prompt?: string; options?: string[] };
        const prompt = typeof parsed.prompt === "string" ? parsed.prompt.trim() : trimmed;
        const options = Array.isArray(parsed.options) ? parsed.options : [];
        if (!options.length) return prompt;
        return `${prompt} 选项: ${options.map((opt) => ` ${opt}`).join(" ")}`;
    } catch {
        return trimmed;
    }
}

function collapseEmptyLines(text: string): string {
    return text.replace(/\n+/g, "\n");
}

export default function WeaknessAnalysisPage() {
    const navigate = useNavigate();
    const { quizId } = useParams<{ quizId?: string }>();
    const [searchParams] = useSearchParams();
    const [quizTitle, setQuizTitle] = useState<string | null>(null);
    const [deckName, setDeckName] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [relatedDecks, setRelatedDecks] = useState<Array<{ id: string; title: string }>>([]);
    const [selectedDeckIds, setSelectedDeckIds] = useState<Set<string>>(new Set());
    const [analysisLoading, setAnalysisLoading] = useState(false);
    const [analysisError, setAnalysisError] = useState<string | null>(null);
    const [analysisResult, setAnalysisResult] = useState<unknown>(null);
    const [relatedEaseMap, setRelatedEaseMap] = useState<Map<string, number | null>>(new Map());
    const [selectedRelatedIds, setSelectedRelatedIds] = useState<Set<string>>(new Set());
    const [showUpdateConfirm, setShowUpdateConfirm] = useState(false);
    const [updatingKnowledge, setUpdatingKnowledge] = useState(false);
    const [statusMessage, setStatusMessage] = useState<string | null>(null);
    const [selectedQuestionPairs, setSelectedQuestionPairs] = useState<QuestionAnswerPair[]>([]);
    const selectedIds = useMemo(() => {
        const raw = searchParams.get("ids") ?? "";
        return raw
            .split(",")
            .map((id) => id.trim())
            .filter(Boolean);
    }, [searchParams]);
    const selectedCount = selectedIds.length;
    const selectedDeckTitles = relatedDecks
        .filter((deck) => selectedDeckIds.has(deck.id))
        .map((deck) => deck.title)
        .join(", ");
    const selectedDeckIdList = Array.from(selectedDeckIds);
    const analysisRows = useMemo(() => {
        if (!Array.isArray(analysisResult)) return [];
        return analysisResult.map((item) => {
            const record = item as {
                card_id?: string;
                analysis?: string;
                related_cards?: Array<{ id?: string; title?: string }>;
            };
            const cardId = record.card_id ?? "";
            const questionFull = selectedQuestionPairs.find((q) => q.card_id === cardId)?.front ?? "";
            const questionSummary = truncateText(questionFull, 24);
            const related = Array.isArray(record.related_cards) ? record.related_cards : [];
            return {
                cardId,
                questionFull,
                questionSummary,
                analysis: record.analysis ?? "",
                relatedCards: related
                    .map((c) => ({
                        id: c?.id ?? "",
                        title: c?.title ?? "",
                    }))
                    .filter((c) => c.title.trim().length > 0),
            };
        });
    }, [analysisResult, selectedQuestionPairs]);

    const relatedAnalysisMap = useMemo(() => {
        const map = new Map<string, Array<{ question_card_id: string; question: string; analysis: string }>>();
        for (const row of analysisRows) {
            for (const card of row.relatedCards) {
                if (!card.id) continue;
                const list = map.get(card.id) ?? [];
                list.push({
                    question_card_id: row.cardId,
                    question: row.questionFull,
                    analysis: row.analysis,
                });
                map.set(card.id, list);
            }
        }
        return map;
    }, [analysisRows]);

    useEffect(() => {
        if (!Array.isArray(analysisResult)) {
            setSelectedRelatedIds(new Set());
            return;
        }
        const ids = new Set<string>();
        for (const row of analysisRows) {
            for (const card of row.relatedCards) {
                if (card.id) ids.add(card.id);
            }
        }
        setSelectedRelatedIds(ids);
    }, [analysisResult, analysisRows]);

    const allRelatedSelected = useMemo(() => {
        if (!analysisRows.length) return false;
        const ids = new Set<string>();
        for (const row of analysisRows) {
            for (const card of row.relatedCards) {
                if (card.id) ids.add(card.id);
            }
        }
        return ids.size > 0 && Array.from(ids).every((id) => selectedRelatedIds.has(id));
    }, [analysisRows, selectedRelatedIds]);

    useEffect(() => {
        if (!Array.isArray(analysisResult)) {
            setRelatedEaseMap(new Map());
            return;
        }
        const ids = new Set<string>();
        for (const item of analysisResult) {
            const rec = item as { related_cards?: Array<{ id?: string }> };
            const cards = Array.isArray(rec.related_cards) ? rec.related_cards : [];
            for (const card of cards) {
                if (card?.id) ids.add(card.id);
            }
        }
        if (!ids.size) {
            setRelatedEaseMap(new Map());
            return;
        }
        let active = true;
        const loadEase = async () => {
            const { data, error } = await supabase
                .from("card_stats")
                .select("card_id, ease_factor")
                .in("card_id", Array.from(ids));
            if (!active) return;
            if (error) {
                console.error("load ease_factor error", error);
                return;
            }
            const map = new Map<string, number | null>();
            for (const row of (data ?? []) as Array<{ card_id: string; ease_factor: number | null }>) {
                map.set(row.card_id, row.ease_factor ?? null);
            }
            setRelatedEaseMap(map);
        };
        void loadEase();
        return () => {
            active = false;
        };
    }, [analysisResult]);

    useEffect(() => {
        if (!quizId) return;
        let active = true;
        const load = async () => {
            setLoading(true);
            const { data, error } = await supabase
                .from("user_active_quizzes")
                .select("title, deck_name")
                .eq("id", quizId)
                .maybeSingle();
            if (!active) return;
            if (error) {
                console.error("load quiz info error", error);
                setLoading(false);
                return;
            }
            setQuizTitle(data?.title ?? null);
            setDeckName(data?.deck_name ?? null);
            setLoading(false);
        };
        void load();
        return () => {
            active = false;
        };
    }, [quizId]);

    useEffect(() => {
        if (!deckName) return;
        let active = true;
        const loadDecks = async () => {
            let decks: Array<{ id: string; title: string }>;
            try {
                decks = await theDeckService.listDecksByPrefix(deckName);
            } catch (error) {
                console.error("load related decks error", error);
                return;
            }
            if (!active) return;
            const filteredDecks = decks.filter((deck) => !deck.title.includes("/_"));
            filteredDecks.sort((a, b) => compareDeckTitlesByPath(a.title, b.title));
            setRelatedDecks(filteredDecks);
            const defaultSelected = new Set<string>();
            const exact = filteredDecks.find((deck) => deck.title === deckName);
            if (exact) defaultSelected.add(exact.id);
            setSelectedDeckIds(defaultSelected);
        };
        void loadDecks();
        return () => {
            active = false;
        };
    }, [deckName]);

    useEffect(() => {
        if (!selectedIds.length) {
            setSelectedQuestionPairs([]);
            return;
        }
        let active = true;
        const loadSelectedQuestions = async () => {
            const [cardsRes, reviewsRes] = await Promise.all([
                supabase
                    .from("cards")
                    .select("id, front, back")
                    .in("id", selectedIds),
                supabase
                    .from("card_reviews")
                    .select("card_id, user_answer, reviewed_at")
                    .in("card_id", selectedIds)
                    .eq("is_question", true)
                    .order("reviewed_at", { ascending: false }),
            ]);
            if (!active) return;
            if (cardsRes.error || reviewsRes.error) {
                console.error("load selected questions error", {
                    cardsError: cardsRes.error,
                    reviewsError: reviewsRes.error,
                });
                return;
            }
            const cardMap = new Map<string, { front: string; back: string }>();
            for (const card of (cardsRes.data ?? []) as Array<{ id: string; front: string; back: string }>) {
                cardMap.set(card.id, {
                    front: card.front ?? "",
                    back: card.back ?? "",
                });
            }
            const reviewMap = new Map<string, string | null>();
            for (const review of (reviewsRes.data ?? []) as Array<{ card_id: string; user_answer: string | null }>) {
                if (!reviewMap.has(review.card_id)) {
                    reviewMap.set(review.card_id, review.user_answer ?? null);
                }
            }
            const ordered = selectedIds.map((id) => {
                const card = cardMap.get(id);
                const frontRaw = card?.front ?? "";
                return {
                    card_id: id,
                    front: buildPromptFull(frontRaw),
                    back: card?.back ?? "",
                    user_answer: reviewMap.get(id) ?? null,
                };
            });
            setSelectedQuestionPairs(ordered);
        };
        void loadSelectedQuestions();
        return () => {
            active = false;
        };
    }, [selectedIds]);

    async function handleAnalyze() {
        if (!selectedDeckIdList.length) return;
        setAnalysisLoading(true);
        setAnalysisError(null);
        setAnalysisResult(null);
        setStatusMessage("正在分析…");
        const questions = selectedQuestionPairs.map((item) => ({
            card_id: item.card_id,
            question: item.front,
            correct_answer: item.back,
            user_answer: item.user_answer,
        }));
        const { data, error } = await supabase.functions.invoke("weakness-analysis", {
            body: {
                questions,
                deck_ids: selectedDeckIdList,
            },
        });
        if (error) {
            console.error("weakness-analysis error", error);
            setAnalysisError("分析失败");
            setStatusMessage("分析失败。");
            setAnalysisLoading(false);
            return;
        }
        setAnalysisResult(data);
        setStatusMessage("分析完成。");
        setAnalysisLoading(false);
    }

    async function handleUpdateKnowledgeStatus() {
        if (!selectedRelatedIds.size) return;
        setUpdatingKnowledge(true);
        const { data: userData } = await supabase.auth.getUser();
        const user = userData.user;
        if (!user) {
            setUpdatingKnowledge(false);
            setShowUpdateConfirm(false);
            return;
        }
        const now = new Date().toISOString();
        const easeFactor = easeFactorFromLevel(2);
        const deckId = selectedDeckIdList[0] ?? null;
        const ids = Array.from(selectedRelatedIds);
        await Promise.all(
            ids.map((cardId) =>
                recordDifficultyUpdate({
                    supabase,
                    userId: user.id,
                    cardId,
                    deckId,
                    easeFactor,
                    reviewedAt: now,
                    timeSpentSeconds: null,
                    isQuestion: false,
                    meta: {
                        difficulty: easeFactor,
                        source: "weakness-analysis",
                        related_questions: relatedAnalysisMap.get(cardId) ?? [],
                    },
                })
            )
        );
        setRelatedEaseMap((prev) => {
            const next = new Map(prev);
            ids.forEach((id) => next.set(id, easeFactor));
            return next;
        });
        setStatusMessage(`已更新 ${ids.length} 张知识卡为“有点难”。`);
        setUpdatingKnowledge(false);
        setShowUpdateConfirm(false);
    }

    return (
        <div className="max-w-3xl mx-auto py-10 px-4 text-slate-900 dark:text-slate-100">
            <div className="mt-1 flex items-center justify-between gap-3">
                <div className="text-xl font-semibold">
                    根据“{quizTitle ?? "测验"}”的 {selectedCount} 道题目分析未掌握的知识点
                </div>
                <div className="flex items-center gap-2">
                    <Button
                        variant="iconRound"
                        className="text-emerald-600 hover:text-white hover:bg-emerald-600 dark:text-emerald-300 dark:hover:text-emerald-100 dark:hover:bg-emerald-700"
                        onClick={() => navigate(quizId ? `/quiz-runs/${quizId}` : "/quiz-runs")}
                        title="返回测验情况"
                    >
                        <ArrowLeft className="w-6 h-6" />
                        <span className="sr-only">返回测验情况</span>
                    </Button>
                    <Button
                        variant="iconRound"
                        className="text-emerald-600 hover:text-white hover:bg-emerald-600 dark:text-emerald-300 dark:hover:text-emerald-100 dark:hover:bg-emerald-700"
                        onClick={() => navigate(`/quizzes?path=${deckName ?? ""}`)}
                        title="返回测验列表"
                    >
                        <CornerUpLeft className="w-6 h-6" />
                        <span className="sr-only">返回测验列表</span>
                    </Button>
                </div>
            </div>
            <div className="mt-6 text-sm text-slate-600 dark:text-slate-300">
                <div className="flex items-center gap-2 text-base font-semibold text-slate-700 dark:text-slate-200 mb-1">
                    <Layers className="h-4 w-4 text-amber-500" />
                    关联卡组
                </div>
                <div className="flex items-stretch gap-4">
                    <div className="w-1/2 rounded-xl border border-slate-200 bg-white p-3 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200">
                        {relatedDecks.length === 0 ? (
                            <div className="text-xs text-slate-500 dark:text-slate-400">
                                暂无可选卡组。
                            </div>
                        ) : (
                            <div className="flex flex-col gap-2">
                                {relatedDecks.map((deck) => {
                                    const selected = selectedDeckIds.has(deck.id);
                                    return (
                                        <button
                                            key={deck.id}
                                            type="button"
                                            aria-pressed={selected}
                                            onClick={() => {
                                                setSelectedDeckIds((prev) => {
                                                    const next = new Set(prev);
                                                    if (selected) {
                                                        next.delete(deck.id);
                                                    } else {
                                                        next.add(deck.id);
                                                    }
                                                    return next;
                                                });
                                            }}
                                            className={
                                                "w-full rounded-full px-3 py-1 text-left text-xs transition-colors " +
                                                (selected
                                                    ? "bg-emerald-600 text-white"
                                                    : "bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700")
                                            }
                                            title={deck.title}
                                        >
                                            {deck.title}
                                        </button>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                    <div className="w-1/2 flex flex-col">
                        <input
                            readOnly
                            value={selectedDeckTitles || (loading ? "加载中..." : "-")}
                            className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-1 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200"
                        />
                        <div className="mt-auto flex items-center justify-between pt-4">
                            <Button
                                type="button"
                                variant="outline"
                                className="px-4 py-1 text-lg"
                                disabled={!selectedDeckTitles || analysisLoading}
                                onClick={handleAnalyze}
                            >
                                {analysisLoading ? (
                                    <span className="relative inline-flex items-center justify-center">
                                        <span className="opacity-0">开始分析</span>
                                        <Loader2 className="absolute inset-0 m-auto h-7 w-7 animate-spin" />
                                    </span>
                                ) : (
                                    "开始分析"
                                )}
                            </Button>
                            {Boolean(analysisResult) && (
                                <Button
                                    type="button"
                                    variant="iconRound"
                                    className="bg-orange-500 text-white hover:bg-orange-600 dark:bg-orange-500 dark:hover:bg-orange-600"
                                    title="更新知识状态"
                                    onClick={() => setShowUpdateConfirm(true)}
                                    disabled={selectedRelatedIds.size === 0 || updatingKnowledge}
                                >
                                    <RefreshCw className="w-6 h-6 text-white" />
                                    <span className="sr-only">更新知识状态</span>
                                </Button>
                            )}
                        </div>
                    </div>
                </div>
            </div>
            <div className="mt-4 text-sm text-slate-600 dark:text-slate-300">
                {statusMessage && (
                    <div className="mb-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-2 text-right text-sm text-slate-700 dark:border-slate-600 dark:bg-slate-900/60 dark:text-slate-200">
                        {statusMessage}
                    </div>
                )}
                <div className="text-slate-700 dark:text-slate-200">
                    {!analysisLoading && analysisError && (
                        <span className="text-rose-600 dark:text-rose-400">{analysisError}</span>
                    )}
                    {!analysisLoading && !analysisError && (
                        <>
                            {!analysisResult ? (
                                <span className="text-slate-500 dark:text-slate-400">暂无分析结果。</span>
                            ) : analysisRows.length > 0 ? (
                                <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white/80 p-3 dark:border-slate-700 dark:bg-slate-900/50">
                                    <table className="w-full text-sm table-auto">
                                        <thead className="text-xs text-slate-500 dark:text-slate-400">
                                            <tr className="border-b border-slate-200 dark:border-slate-700">
                                                <th className="py-2 text-left font-medium w-[30%]">题目</th>
                                                <th className="py-2 text-left font-medium w-[40%]">考查点及错因分析</th>
                                                <th className="py-2 text-left font-medium w-[30%] bg-slate-100 dark:bg-slate-800">
                                                    <div className="flex items-center justify-between gap-2 px-2">
                                                        <span>相关知识</span>
                                                        <input
                                                            type="checkbox"
                                                            checked={allRelatedSelected}
                                                            onChange={(e) => {
                                                                setSelectedRelatedIds((prev) => {
                                                                    const next = new Set(prev);
                                                                    if (e.target.checked) {
                                                                        analysisRows.forEach((row) => {
                                                                            row.relatedCards.forEach((card) => {
                                                                                if (card.id) next.add(card.id);
                                                                            });
                                                                        });
                                                                    } else {
                                                                        analysisRows.forEach((row) => {
                                                                            row.relatedCards.forEach((card) => {
                                                                                if (card.id) next.delete(card.id);
                                                                            });
                                                                        });
                                                                    }
                                                                    return next;
                                                                });
                                                            }}
                                                            aria-label="全选相关知识"
                                                        />
                                                    </div>
                                                </th>
                                            </tr>
                                        </thead>
                                        <tbody className="text-slate-700 dark:text-slate-300">
                                            {analysisRows.map((row, idx) => (
                                                <tr key={`${row.cardId}-${idx}`} className="border-b border-slate-100 dark:border-slate-800 align-top">
                                                    <td className="py-2 pr-3">
                                                        {row.questionSummary ? (
                                                            <span title={row.questionFull}>
                                                                {row.questionSummary}
                                                            </span>
                                                        ) : (
                                                            row.cardId || "—"
                                                        )}
                                                    </td>
                                                    <td className="py-2 pr-3 whitespace-pre-wrap text-slate-600 dark:text-slate-300">
                                                        {row.analysis ? collapseEmptyLines(row.analysis) : "—"}
                                                    </td>
                                                    <td className="py-2">
                                                        {row.relatedCards.length ? (
                                                            <div className="space-y-1">
                                                                {row.relatedCards.map((card, idx) => {
                                                                    const colorClass = easeFactorToColor(
                                                                        relatedEaseMap.get(card.id)
                                                                    );
                                                                    return (
                                                                        <div
                                                                            key={`${row.cardId}-${idx}`}
                                                                            className="flex items-center gap-2 rounded-md bg-slate-100 px-2 py-1 text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-200"
                                                                        >
                                                                            <span className={`h-3 w-3 rounded-full ${colorClass}`} />
                                                                            <span className="flex-1" title={card.title}>
                                                                                {truncateText(card.title, 10)}
                                                                            </span>
                                                                            <input
                                                                                type="checkbox"
                                                                                checked={selectedRelatedIds.has(card.id)}
                                                                                onChange={(e) => {
                                                                                    setSelectedRelatedIds((prev) => {
                                                                                        const next = new Set(prev);
                                                                                        if (e.target.checked) {
                                                                                            next.add(card.id);
                                                                                        } else {
                                                                                            next.delete(card.id);
                                                                                        }
                                                                                        return next;
                                                                                    });
                                                                                }}
                                                                                aria-label={`选择知识点 ${card.title}`}
                                                                            />
                                                                        </div>
                                                                    );
                                                                })}
                                                            </div>
                                                        ) : (
                                                            "—"
                                                        )}
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            ) : (
                                <span className="text-slate-500 dark:text-slate-400">分析结果格式异常。</span>
                            )}
                        </>
                    )}
                </div>
            </div>
            <ConfirmDialog
                open={showUpdateConfirm}
                title="更新知识状态"
                description={`是否要将 ${selectedRelatedIds.size} 张知识卡的状态更新为“有点难”，用于后续巩固知识？`}
                confirmLabel="确认更新"
                cancelLabel="取消"
                loading={updatingKnowledge}
                onCancel={() => {
                    if (!updatingKnowledge) setShowUpdateConfirm(false);
                }}
                onConfirm={() => {
                    void handleUpdateKnowledgeStatus();
                }}
            />
        </div>
    );
}
