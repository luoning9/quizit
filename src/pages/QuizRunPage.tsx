import {useEffect, useMemo, useState} from "react";
import {useNavigate, useParams} from "react-router-dom";
import {supabase} from "../../lib/supabaseClient";
import {BookOpen, Loader2, CheckCircle, XCircle} from "lucide-react";
import {type QuizTemplate, renderPrompt, renderAnswer, renderFinishedArea, type QuizRunResult} from "./quizRenderer";
import {
    type BackSchema,
    checkAnswer,
    type FrontSchema,
    parseBack,
    parseFront,
    type UserAnswer
} from "../../lib/quizFormat.ts";
import { useTimer } from "../components/TimerContext";  // ← 新增，路径和 AppLayout 一致
import { Button } from "../components/ui/Button";

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

    const [currentIndex, setCurrentIndex] = useState(0);
    const [showAnswer, setShowAnswer] = useState(false);
    const [finished, setFinished] = useState(false);
    const [hasSubmitted, setHasSubmitted] = useState(false);

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

            // 1. 读取 quiz_templates
            const {data: tmpl, error: tmplError} = await supabase
                .from("quiz_templates")
                .select("id, title, description, items")
                .eq("id", templateId)
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
                item_ids: orderedItems.map((it: { card_id: string; position: number }) => it.card_id) ?? [],
            };
            setTemplate(typedTemplate);
            //console.log(typedTemplate);

            if (!typedTemplate.item_ids.length) {
                setQuestions([]);
                setLoading(false);
                return;
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

    const totalQuestions = questions.length;
    const currentQuestion = questions[currentIndex] ?? null;

    const currentCorrect = useMemo(() => {
        if (!currentQuestion || !runResult) return null;
        const rec = runResult.answers.find((it) => it.cardId === currentQuestion.cardId);
        return rec?.isCorrect ?? null;
    }, [runResult, currentQuestion]);
    // 存储测验结果
    const [resultSaved, setResultSaved] = useState(false);
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
                template_id: template?.id ?? null,
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

            const { error } = await supabase
                .from("quiz_runs")
                .insert(quizData)
                .select()
                .single();

            if (error) {
                console.error("保存测验结果失败:", error);
            }
            setResultSaved(true);
        };
        void saveResult();
    }, [finished, runResult, userId, template, resultSaved]);

    // ===== 2. 用户作答逻辑 =====
    function handleSubmitAnswer() {
        if (!currentQuestion) return;

        // 用统一的 string[] UserAnswer 判分
        const isCorrect = checkAnswer(
            currentQuestion.front,
            currentQuestion.back,
            currentUserAnswer
        );
        // 2) Fire-and-forget 异步写入 card_reviews
        void (async () => {
            const reviewData = {
                user_id: userId,
                card_id: currentQuestion.cardId,
                user_answer: JSON.stringify(currentUserAnswer),
                is_correct: isCorrect,
                time_spent: null,
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
        }
    }

    // ===== 3. 状态渲染 =====
    if (loading) {
        return (
            <div className="flex flex-col items-center justify-center py-12 text-slate-300">
                <Loader2 className="w-6 h-6 animate-spin mb-3"/>
                正在加载测验…
            </div>
        );
    }

    if (loadingError) {
        return (
            <div className="flex flex-col items-center justify-center py-12 text-slate-300">
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
            <div className="flex flex-col items-center justify-center py-12 text-slate-300">
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
        return renderFinishedArea(template, runResult, resultSaved);
    }

    // ===== 5. 正常做题界面 =====

    return (
        <div className="w-fit max-w-4xl mx-auto py-8 px-4">
            {/* 头部 */}
            <header className="mb-6 flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                    <BookOpen className="w-7 h-7 text-sky-400"/>
                    <div>
                        <div className="text-xl font-semibold text-white">
                            {template.title}
                        </div>
                        {template.description && (
                            <div className="text-xs text-slate-400 mt-1">
                                {template.description}
                            </div>
                        )}
                    </div>
                </div>
                <div className="text-xs text-slate-400">
                    题目 {currentIndex + 1} / {totalQuestions}
                </div>
            </header>

            {/* 题卡 + 右侧按钮 */}
            <div className="w-full flex items-start gap-4 mb-6">
                {/* 问题卡片 */}
                <div className="min-h-32 flex-1 min-w-0 rounded-2xl border border-slate-700 bg-slate-900/80 p-6">
                    <div className="text-xs text-slate-400 mb-2">题目</div>
                    <div className="text-base text-slate-50">
                        {currentQuestion &&
                            renderPrompt(currentQuestion.front, {
                                userAnswer: currentUserAnswer,
                                setUserAnswer: setCurrentUserAnswer,
                                disabled: hasSubmitted, // 提交后禁止修改
                            })}
                    </div>

                    {showAnswer && (
                        <div className="mt-6 border-t border-slate-700 pt-4">
                            <div className="text-xs text-slate-400 mb-1">答案</div>
                            {renderAnswer(currentQuestion.front, currentQuestion.back)}
                        </div>
                    )}


                </div>
                <div className="flex flex-col justify-center flex-none">
                    {/* ----- 这里是大图标区域 ----- */}
                    <div className="h-18 flex justify-center">
                        {showAnswer && currentCorrect && (
                            <CheckCircle className="w-14 h-14 text-emerald-500 drop-shadow-lg" />
                        )}
                        {showAnswer && !currentCorrect && (
                            <XCircle className="w-14 h-14 text-red-500 drop-shadow-lg" />
                        )}
                    </div>
                    {/* 统一一个按钮：未显示答案时是“提交答案”，显示答案后变成“下一题” */}
                    <Button
                        type="button"
                        variant={showAnswer ? "primary" : "outline"}
                        className={showAnswer ? "w-40 text-2xl" : "w-40 text-lg"}
                        onClick={showAnswer ? handleNextQuestion : handleSubmitAnswer}
                    >
                        {showAnswer ? "➤" : "提交答案"}
                    </Button>
                </div>
            </div>

        </div>
    );
}

export default QuizRunPage;
