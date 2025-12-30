import {useEffect, useMemo, useState, useRef} from "react";
import {useNavigate, useParams} from "react-router-dom";
import {supabase} from "../../lib/supabaseClient";
import {BookOpen, Loader2, CheckCircle, XCircle, CornerUpLeft} from "lucide-react";
import {type QuizTemplate, renderPrompt, renderAnswer, type QuizRunResult} from "./quizRenderer";
import {
    type BackSchema,
    checkAnswer,
    countBlanks,
    type FrontSchema,
    parseBack,
    parseFront,
    type UserAnswer
} from "../../lib/quizFormat.ts";
import { useTimer } from "../components/TimerContext";  // ← 新增，路径和 AppLayout 一致
import { Button } from "../components/ui/Button";
import { addCardToWrongBook } from "../../lib/WrongBook.ts";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { differenceInSeconds } from "date-fns";
import MarkdownText from "../components/MarkdownText";

interface QuizQuestion {
    cardId: string;
    /** 本题在测验模板中的顺序，从 1 开始 */
    position: number;
    /** 本题的分值，来自 front.score，若 front 没写则默认 1 */
    score: number;

    frontRaw: string;
    backRaw: string;
    front: FrontSchema;
    back: BackSchema;
}

function QuizRunPage() {
    const [userId, setUserId] = useState<string | null>(null);

    useEffect(() => {
        async function loadUser() {
            const {
                data: { user },
            } = await supabase.auth.getUser();
            setUserId(user?.id ?? null);
        }
        loadUser();
    }, []);

    const {templateId} = useParams<{ templateId: string }>();
    const navigate = useNavigate();
    // 计时器：全局顶栏那个
    const { start, pause, reset } = useTimer();

    const [template, setTemplate] = useState<QuizTemplate | null>(null);
    const [questions, setQuestions] = useState<QuizQuestion[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadingError, setLoadingError] = useState<string | null>(null);
    const [frontMediaMap, setFrontMediaMap] = useState<Record<string, string[]>>({});

    const [currentIndex, setCurrentIndex] = useState(0);
    const [showAnswer, setShowAnswer] = useState(false);
    const [finished, setFinished] = useState(false);
    const [hasSubmitted, setHasSubmitted] = useState(false);
    const actionBtnRef = useRef<HTMLButtonElement | null>(null);
    const [showFloatingAction, setShowFloatingAction] = useState(false);
    const [floatingPos, setFloatingPos] = useState<{ left: number; top: number } | null>(null);
    const questionStartRef = useRef<Date | null>(null);
    const [showMaterial, setShowMaterial] = useState(true);

    // 当前题目的作答：统一 string[]，初始为空数组
    const [currentUserAnswer, setCurrentUserAnswer] = useState<UserAnswer>([]);
    // 用来记录每题是否答对（统计用，可选）
    const [runResult, setRunResult] = useState<QuizRunResult | null>(null);
    // ===== 1. 加载模板 & 题目 =====
    useEffect(() => {
        async function loadQuiz() {
            if (!templateId) {
                setLoadingError("缺少测验模板 ID。");
                setLoading(false);
                return;
            }

            setLoading(true);
            setLoadingError(null);
            setFrontMediaMap({});

            // 1. 读取 quizzes（旧名 quiz_templates）
            const {data: tmpl, error: tmplError} = await supabase
                .from("quizzes")
                .select("id, title, description, deck_name, items")
                .eq("id", templateId)
                .eq("is_deleted", false)
                .maybeSingle();

            if (tmplError || !tmpl) {
                console.error("load quiz_template error", tmplError);
                setLoadingError("未找到对应的测验模板。");
                setLoading(false);
                return;
            }

            const orderedItems = (tmpl.items?.items ?? []).slice().sort(
                (a: { position: number }, b:{ position: number }) => a.position - b.position
            );
            const typedTemplate: QuizTemplate = {
                id: tmpl.id,
                title: tmpl.title,
                description: tmpl.description,
                deck_name: tmpl.deck_name ?? '',
                item_ids: orderedItems.map((it: { card_id: string; position: number }) => it.card_id) ?? [],
            };
            setTemplate(typedTemplate);
            //console.log(typedTemplate);

            if (!typedTemplate.item_ids.length) {
                setQuestions([]);
                setLoading(false);
                return;
            }

            // 1.5 尝试在 storage 中找 front 媒体（如 {card_id}/front*.png）
            try {
                const mediaEntries = await Promise.all(
                    typedTemplate.item_ids.map(async (cid) => {
                        const { data: list, error: listErr } = await supabase
                            .storage
                            .from("quizit_card_medias")
                            .list(`${cid}`);
                        if (listErr || !list) return { cid, urls: [] as string[] };

                        const frontPaths = list
                            .filter((f) => f.name.toLowerCase().startsWith("front"))
                            .map((f) => `${cid}/${f.name}`);
                        if (!frontPaths.length) return { cid, urls: [] as string[] };

                        const { data: signedData, error: signedErr } = await supabase
                            .storage
                            .from("quizit_card_medias")
                            .createSignedUrls(frontPaths, 600);
                        if (signedErr || !signedData) return { cid, urls: [] as string[] };

                        const urls = signedData
                            .map((item) => item.signedUrl)
                            .filter((u): u is string => Boolean(u));
                        return { cid, urls };
                    })
                );

                const mediaMap: Record<string, string[]> = {};
                mediaEntries.forEach(({ cid, urls }) => {
                    if (urls.length) {
                        mediaMap[cid] = urls;
                    }
                });
                setFrontMediaMap(mediaMap);
            } catch (e) {
                console.error("加载题目媒体失败", e);
            }

            //const cardIds = itemList.map((it) => it.card_id);

            // 2. 根据 card_id 读取 cards
            const {data: cardsData, error: cardsError} = await supabase
                .from("cards")
                .select("id, front, back")
                .in("id", typedTemplate.item_ids);

            if (cardsError || !cardsData) {
                console.error("load cards error", cardsError);
                setLoadingError("加载题目卡片失败。");
                setLoading(false);
                return;
            }

            const questions: QuizQuestion[] = typedTemplate.item_ids
                .map((id, index) => {
                    const found = cardsData.find((c) => c.id === id);
                    if (!found) return null;

                    const frontParsed = parseFront(found.front);
                    const backParsed = parseBack(found.back);

                    return {
                        cardId: found.id,
                        position: index + 1,                 // ← 自动根据顺序生成
                        score: frontParsed.score ?? 1,       // ← 解析后的 front 里取 score
                        frontRaw: found.front,
                        backRaw: found.back,
                        front: frontParsed,
                        back: backParsed,
                    } satisfies QuizQuestion;
                })
                .filter((q): q is QuizQuestion => q !== null);

            questions.forEach((q) => {
                console.debug("quiz front", q.cardId, q.front);
            });

            setQuestions(questions);
            // 初始化测验结果
            setRunResult({
                startedAt: new Date().toISOString(),
                finishedAt: null,
                answers: questions.map((q) => ({
                    cardId: q.cardId,
                    score: q.score,
                    isCorrect: false,  // 初始值
                    answer: null,
                })),
            });
            setCurrentIndex(0);
            setCurrentUserAnswer([]);
            setHasSubmitted(false);
            setShowAnswer(false);
            //setAnswers([]);
            setFinished(false);
            setLoading(false);
            questionStartRef.current = new Date();
        }

        loadQuiz();
    }, [templateId]);

    useEffect(() => {
        reset();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
// ② showAnswer 控制计时器运行/暂停
    useEffect(() => {
        if (showAnswer) {
            pause();   // 看答案 → 暂停计时
        } else {
            start();   // 做题阶段 → 开始计时
        }
    }, [showAnswer, start, pause]);
    useEffect(() => {
        const updateFloating = () => {
            const btn = actionBtnRef.current;
            if (!btn) return;
            const rect = btn.getBoundingClientRect();
            const isVisible = rect.top >= 0 && rect.bottom <= window.innerHeight;
            setShowFloatingAction(!isVisible);
            const top = Math.min(Math.max(rect.bottom + 12, 12), window.innerHeight - 60);
            setFloatingPos({ left: rect.left, top });
        };
        updateFloating();
        window.addEventListener("scroll", updateFloating, { passive: true });
        window.addEventListener("resize", updateFloating, { passive: true });
        return () => {
            window.removeEventListener("scroll", updateFloating);
            window.removeEventListener("resize", updateFloating);
        };
    }, []);

    const totalQuestions = questions.length;
    const currentQuestion = questions[currentIndex] ?? null;
    useEffect(() => {
        questionStartRef.current = new Date();
    }, [currentQuestion?.cardId]);

    const currentCorrect = useMemo(() => {
        if (!currentQuestion || !runResult) return null;
        const rec = runResult.answers.find((it) => it.cardId === currentQuestion.cardId);
        return rec?.isCorrect ?? null;
    }, [runResult, currentQuestion]);
    // 存储测验结果
    const [resultSaved, setResultSaved] = useState(false);
    const [wrongReason, setWrongReason] = useState("");
    const [checkingAnswer, setCheckingAnswer] = useState(false);
    const [showExitConfirm, setShowExitConfirm] = useState(false);
    useEffect(() => {
        if (!finished || !runResult || !userId || resultSaved) return;

        const saveResult = async () => {
            const totalQuestions = runResult.answers.length;
            const correctCount = runResult.answers.filter((it) => it.isCorrect).length;
            const earned = runResult.answers
                .filter((it) => it.isCorrect)
                .reduce((sum, it) => sum + it.score, 0);

            const total = runResult.answers
                .reduce((sum, it) => sum + it.score, 0);

            const scoreRatio = total > 0 ? earned / total : 0;

            const quizData = {
                template_id: template?.id ?? templateId ?? null,
                user_id: userId,
                started_at: runResult.startedAt,
                finished_at: runResult.finishedAt ?? new Date().toISOString(),
                score: scoreRatio,
                total_items: totalQuestions,
                correct_items: correctCount,
                config: {
                    items: runResult.answers,
                },
            };

            const { data: inserted, error } = await supabase
                .from("quiz_runs")
                .insert(quizData)
                .select()
                .single();

            if (error) {
                console.error("保存测验结果失败:", error);
                return;
            }
            setResultSaved(true);
            if (inserted?.id) {
                navigate(`/quiz-runs/${template?.id ?? templateId ?? "unknown"}/${inserted.id}`);
            }
        };
        void saveResult();
    }, [finished, runResult, userId, template, resultSaved, navigate, templateId]);

    // ===== 2. 用户作答逻辑 =====
    async function handleSubmitAnswer() {
        if (!currentQuestion) return;
        const { front, back } = currentQuestion;

        let isCorrect = false;

        if (front.type === "basic") {
            // Basic: 优先使用 edge function 做语义判题，失败再回落本地规则
            // 优先调用 edge function 进行判题
            const standardAnswer = back.answers?.[0]?.[0] ?? "";
            const userText = currentUserAnswer ? currentUserAnswer[0] : "";
            if (standardAnswer && userText) {
                setCheckingAnswer(true);
                try {
                    const { data, error } = await supabase.functions.invoke("check-answer", {
                        body: {
                            standardAnswer,
                            userAnswer: userText,
                        },
                    });
                    if (!error && data && typeof data.correct === "boolean") {
                        isCorrect = data.correct;
                        if (!isCorrect && typeof data.reason === "string") {
                            setWrongReason(data.reason);
                        } else if (isCorrect) {
                            setWrongReason("");
                        }
                    } else {
                        console.warn("check-answer invoke failed, fallback to local check", error);
                        isCorrect = checkAnswer(front, back, currentUserAnswer);
                        setWrongReason("");
                    }
                } catch (err) {
                    console.error("check-answer invoke error", err);
                    isCorrect = checkAnswer(front, back, currentUserAnswer);
                    setWrongReason("");
                } finally {
                    setCheckingAnswer(false);
                }
            } else {
                isCorrect = false;
                setWrongReason("");
            }
        } else if (front.type === "fill_in_blank") {
            // Fill-in-blank: 先本地严格判题，失败后再用 edge function 做语义判题
            isCorrect = checkAnswer(front, back, currentUserAnswer);
            if (!isCorrect) {
                const prompt = front.prompt ?? "";
                const slots = back.answers ?? [];
                const blankCount = prompt ? countBlanks(prompt) : 0;
                let standardAnswers: string[] = [];

                // 特殊情况：多空但答案只有一组时，拆为每空一个标准答案
                if (blankCount > 1 && slots.length === 1) {
                    const flat = slots[0] ?? [];
                    standardAnswers = flat.slice(0, blankCount);
                } else {
                    standardAnswers = slots.map((slot) => slot?.[0] ?? "");
                }

                // 去掉空字符串，若数量不足则直接判错且不调用 edge
                const userAnswers = Array.isArray(currentUserAnswer)
                    ? currentUserAnswer.map((ans) => ans?.trim()).filter((ans) => ans)
                    : [];
                if (blankCount && userAnswers.length < blankCount) {
                    setWrongReason("答案数量不足");
                } else if (prompt && standardAnswers.length > 0 && userAnswers.length > 0) {
                    // 仅在具备完整输入时才调用 edge function
                    setCheckingAnswer(true);
                    try {
                        const { data, error } = await supabase.functions.invoke("check-fill-blank", {
                            body: {
                                prompt,
                                standardAnswers,
                                userAnswers,
                            },
                        });
                        if (!error && data && typeof data.correct === "boolean") {
                            isCorrect = data.correct;
                            if (!isCorrect && typeof data.reason === "string") {
                                setWrongReason(data.reason);
                            } else if (isCorrect) {
                                setWrongReason("");
                            }
                        } else {
                            console.warn("check-fill-blank invoke failed, keep local result", error);
                            setWrongReason("");
                        }
                    } catch (err) {
                        console.error("check-fill-blank invoke error", err);
                        setWrongReason("");
                    } finally {
                        setCheckingAnswer(false);
                    }
                } else {
                    setWrongReason("");
                }
            } else {
                setWrongReason("");
            }
        } else {
            // 其他题型使用本地判题
            isCorrect = checkAnswer(front, back, currentUserAnswer);
            setWrongReason("");
        }
        // 2) Fire-and-forget 异步写入 card_reviews
        void (async () => {
            const timeSpentSeconds =
                questionStartRef.current && !Number.isNaN(questionStartRef.current.getTime())
                    ? Math.max(0, differenceInSeconds(new Date(), questionStartRef.current))
                    : null;
            const reviewData = {
                user_id: userId,
                card_id: currentQuestion.cardId,
                user_answer: JSON.stringify(currentUserAnswer),
                is_correct: isCorrect,
                time_spent: timeSpentSeconds,
                belongs_to: template?.id ?? null,
                is_question: true,
                meta: {
                    position: currentQuestion.position,
                    score: currentQuestion.score,
                    type: currentQuestion.front.type,
                },
            };

            const { error } = await supabase
                .from("card_reviews")
                .insert(reviewData);

            if (error) {
                console.error("插入 card_reviews 失败：", error);
            }

            // 同步更新/插入 card_stats
            if (!userId) return;
            const now = new Date().toISOString();
            const { data: existing, error: statErr } = await supabase
                .from("card_stats")
                .select("id, review_count, correct_count, wrong_count")
                .eq("user_id", userId)
                .eq("card_id", currentQuestion.cardId)
                .maybeSingle();

            if (statErr) {
                console.error("查询 card_stats 失败：", statErr);
                return;
            }

            const baseReview = Number(existing?.review_count ?? 0);
            const baseCorrect = Number(existing?.correct_count ?? 0);
            const baseWrong = Number(existing?.wrong_count ?? 0);

            if (existing?.id) {
                const { error: updateErr } = await supabase
                    .from("card_stats")
                    .update({
                        review_count: baseReview + 1,
                        correct_count: baseCorrect + (isCorrect ? 1 : 0),
                        wrong_count: baseWrong + (isCorrect ? 0 : 1),
                        last_reviewed_at: now,
                        ease_factor: isCorrect ? 3.5 : 1.5,
                    })
                    .eq("id", existing.id);
                if (updateErr) {
                    console.error("更新 card_stats 失败：", updateErr);
                }
            } else {
                const { error: insertErr } = await supabase
                    .from("card_stats")
                    .insert({
                        user_id: userId,
                        card_id: currentQuestion.cardId,
                        review_count: 1,
                        correct_count: isCorrect ? 1 : 0,
                        wrong_count: isCorrect ? 0 : 1,
                        last_reviewed_at: now,
                        ease_factor: isCorrect ? 3.5 : 1.5,
                    });
                if (insertErr) {
                    console.error("插入 card_stats 失败：", insertErr);
                }
            }
        })();

        setRunResult((prev) => {
            if (!prev) return prev;

            const answers = [...prev.answers];
            answers[currentIndex] = {
                ...answers[currentIndex],
                isCorrect,
                answer: currentUserAnswer,
            };

            return {
                ...prev,
                answers,
            };
        });
        setShowAnswer(true);
        setHasSubmitted(true);
    }

    function handleNextQuestion() {
        if (!currentQuestion) return;

        setWrongReason("");
        const nextIndex = currentIndex + 1;

        if (nextIndex >= totalQuestions) {
            setFinished(true);
            setRunResult((prev) =>
                prev
                    ? { ...prev, finishedAt: new Date().toISOString() }
                    : prev
            );
        } else {
            setCurrentIndex(nextIndex);
            setCurrentUserAnswer([]);
            setHasSubmitted(false);
            setShowAnswer(false);
            questionStartRef.current = new Date();
        }
    }

    // ===== 3. 状态渲染 =====
    if (loading) {
        return (
            <div className="flex flex-col items-center justify-center py-12 text-slate-700 dark:text-slate-300">
                <Loader2 className="w-6 h-6 animate-spin mb-3"/>
                正在加载测验…
            </div>
        );
    }

    if (loadingError) {
        return (
            <div className="flex flex-col items-center justify-center py-12 text-slate-700 dark:text-slate-300">
                <div className="mb-2">{loadingError}</div>
                <Button
                    type="button"
                    variant="secondary"
                    className="mt-2 px-4 py-2 rounded-xl text-sm"
                    onClick={() => navigate("/quizzes")}
                >
                    返回测验列表
                </Button>
            </div>
        );
    }

    if (!template || !totalQuestions) {
        return (
            <div className="flex flex-col items-center justify-center py-12 text-slate-700 dark:text-slate-300">
                <div className="mb-2">该测验暂无题目。</div>
                <Button
                    type="button"
                    variant="secondary"
                    className="mt-2 px-4 py-2 rounded-xl text-sm"
                    onClick={() => navigate("/quizzes")}
                >
                    返回测验列表
                </Button>
            </div>
        );
    }

    // ===== 4. 完成状态界面 =====
    if (finished) {
        return (!resultSaved && (
            <div className="text-xs text-slate-500 dark:text-slate-500">
                正在保存测验结果，请稍候…
            </div>
        ))
    }

    // ===== 5. 正常做题界面 =====

    const handleExitConfirm = () => {
        const pathParam = template?.deck_name ? `?path=${encodeURIComponent(template.deck_name)}` : "";
        setShowExitConfirm(false);
        navigate(`/quizzes${pathParam}`);
    };

    return (
        <div className="w-fit max-w-4xl mx-auto py-8 px-4 text-slate-900 dark:text-slate-100">
            {/* 头部 */}
            <header className="mb-6 flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                    <BookOpen className="w-7 h-7 text-emerald-600 dark:text-sky-400"/>
                    <div>
                        <div className="text-xl font-semibold text-slate-900 dark:text-white">
                            {template.title}
                        </div>
                        {template.description && (
                            <div className="text-xs text-slate-600 dark:text-slate-400 mt-1">
                                {template.description}
                            </div>
                        )}
                    </div>
                </div>
                <div className="flex items-center gap-3 text-xs text-slate-600 dark:text-slate-400">
                    <span>题目 {currentIndex + 1} / {totalQuestions}</span>
                    <Button
                        type="button"
                        variant="iconRound"
                        className="text-rose-500 hover:text-white hover:bg-rose-500 dark:text-rose-300 dark:hover:text-rose-100 dark:hover:bg-rose-700"
                        onClick={() => setShowExitConfirm(true)}
                        title="退出测验"
                    >
                        <CornerUpLeft className="w-8 h-8" />
                    </Button>
                </div>
            </header>

            {currentQuestion?.front?.material?.trim() && (
                <div className="w-full rounded-2xl border border-slate-200 bg-white shadow-sm p-5 mb-4 dark:border-slate-700 dark:bg-slate-900/80">
                    <div className="flex items-center justify-between border-b border-slate-200 pb-2 mb-3 dark:border-slate-700">
                        <div className="text-sm font-semibold text-slate-600 dark:text-slate-400">题目材料</div>
                        <button
                            type="button"
                            className="text-xs text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
                            onClick={() => setShowMaterial((prev) => !prev)}
                        >
                            {showMaterial ? "收起" : "展开"}
                        </button>
                    </div>
                    {showMaterial && (
                        <div className="text-base text-slate-800 dark:text-slate-100">
                            <MarkdownText content={currentQuestion.front.material.trim()} />
                        </div>
                    )}
                </div>
            )}
            {/* 题卡 + 右侧按钮 */}
            <div className="w-full flex items-start gap-4 mb-6">
                {/* 问题卡片 */}
                <div className="min-h-32 flex-1 min-w-[320px] rounded-2xl border border-slate-200 bg-white shadow-sm p-6 dark:border-slate-700 dark:bg-slate-900/80">
                    <div className="text-xs text-slate-600 dark:text-slate-400 mb-2">{currentQuestion.cardId}</div>
                    <div className="text-base text-slate-900 dark:text-slate-50">
                        {currentQuestion &&
                            renderPrompt(currentQuestion.front, {
                                userAnswer: currentUserAnswer,
                                setUserAnswer: setCurrentUserAnswer,
                                disabled: hasSubmitted, // 提交后禁止修改
                                frontMediaUrls: frontMediaMap[currentQuestion.cardId],
                            })}
                    </div>

                    {showAnswer && (
                        <div className="mt-6 border-t border-slate-200 pt-4 dark:border-slate-700">
                            <div className="text-xs text-slate-600 dark:text-slate-400 mb-1">答案</div>
                            {renderAnswer(currentQuestion.front, currentQuestion.back)}
                        </div>
                    )}


                </div>
                <div className="flex flex-col justify-center flex-none">
                    {/* ----- 这里是大图标区域 ----- */}
                    <div className="h-18 flex justify-center items-center">
                        {showAnswer && currentCorrect && (
                            <CheckCircle className="w-14 h-14 text-emerald-500 drop-shadow-lg" />
                        )}
                        {showAnswer && !currentCorrect && (
                            <XCircle className="w-14 h-14 text-red-500 drop-shadow-lg" />
                        )}
                        {!showAnswer && checkingAnswer && (
                            <Loader2 className="w-8 h-8 animate-spin text-amber-500" />
                        )}
                    </div>
                    {wrongReason && (
                        <div className="w-40 mt-2 text-sm text-amber-500 dark:text-amber-300 whitespace-normal break-words">
                            {wrongReason}
                        </div>
                    )}
                    {/* 统一一个按钮：未显示答案时是“提交答案”，显示答案后变成“下一题” */}
                    {!(showAnswer && currentCorrect === false) && (
                        <Button
                            variant={showAnswer ? "primary" : "outline"}
                            className={showAnswer ? "w-40 text-2xl" : "w-40 text-lg"}
                            ref={actionBtnRef}
                            onClick={showAnswer ? handleNextQuestion : handleSubmitAnswer}
                        >
                            {showAnswer ? "➤" : "提交答案"}
                        </Button>
                    )}
                    {showAnswer && currentCorrect === false && (
                        <div className="mt-3 grid grid-cols-2 gap-2">
                            <Button
                                type="button"
                                variant="none"
                                onClick={() => {
                                    if (currentQuestion) {
                                        void addCardToWrongBook(template?.deck_name ?? "", currentQuestion.cardId);
                                    }
                                    handleNextQuestion();
                                }}
                                className="bg-orange-500 hover:bg-orange-600 text-slate-100 px-4 py-2 rounded font-normal"
                            >
                                太难了
                            </Button>
                            <Button
                                type="button"
                                variant="none"
                                onClick={handleNextQuestion}
                                className="bg-blue-500 hover:bg-blue-600 text-slate-100 px-4 py-2 rounded font-normal"
                            >
                                大意了
                            </Button>
                        </div>
                    )}
                </div>
            </div>

            {showFloatingAction && (
                <div className="fixed z-40" style={{
                    left: floatingPos?.left ?? 0,
                    top: Math.max(floatingPos?.top ?? window.innerHeight / 2, window.innerHeight / 2),
                }}>
                    <Button
                        type="button"
                        variant={showAnswer ? "primary" : "outline"}
                        className={showAnswer ? "w-40 text-2xl" : "w-40 text-lg shadow-lg border-dashed"}
                        onClick={() => {
                            (showAnswer ? handleNextQuestion : handleSubmitAnswer)();
                            setShowFloatingAction(false);
                            window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                    >
                        {showAnswer ? "➤" : "提交答案"}
                    </Button>
                </div>
            )}

            <ConfirmDialog
                open={showExitConfirm}
                title="退出测验"
                description="确定要退出测验并返回列表吗？"
                onConfirm={handleExitConfirm}
                onCancel={() => setShowExitConfirm(false)}
            />
        </div>
    );
}

export default QuizRunPage;
