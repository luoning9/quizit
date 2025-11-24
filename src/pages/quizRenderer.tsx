import {
    type FrontSchema,
    type BackSchema,
    type UserAnswer,
    indexToLetter,
    countBlanks,
} from "../../lib/quizFormat";
import {BookOpen} from "lucide-react";
import {Link} from "react-router-dom";

type PromptRenderOptions = {
    userAnswer: UserAnswer;
    setUserAnswer?: (next: UserAnswer) => void;
    disabled?: boolean;
};

/**
 * 渲染题干 + 答题区域
 *
 * - 如果不传 setUserAnswer，只显示题干（纯展示模式）
 * - 如果传入 setUserAnswer，则根据题型渲染对应的答题控件
 *   - basic: 文本框
 *   - single_choice: 选项左侧带单选按钮
 *   - multiple_choice: 选项左侧带复选框
 *   - fill_in_blank: 多个填空输入框
 */
export function renderPrompt(
    front: FrontSchema,
    options?: PromptRenderOptions
) {
    const { type } = front;
    const userAnswer: UserAnswer = options?.userAnswer ?? [];
    const disabled = options?.disabled ?? false;
    const setUserAnswer = options?.setUserAnswer;

    // ===== 仅题干文本部分 =====
    const renderPromptText = () => {
        switch (type) {
            case "basic":
            case "single_choice":
            case "multiple_choice":
                return (
                    <p className="whitespace-pre-wrap">
                        {front.prompt}
                    </p>
                );

            case "fill_in_blank": {
                const rendered = front.prompt.replace(/\{\{\d+}}/g, (m) => {
                    const num = m.match(/\d+/)?.[0] ?? "";
                    return `____(${num})____`;
                });

                return (
                    <p className="whitespace-pre-wrap">
                        {rendered}
                    </p>
                );
            }

            default:
                return (
                    <p className="whitespace-pre-wrap">
                        {front.prompt}
                    </p>
                );
        }
    };

    // 如果没传 setUserAnswer，只展示题干，不渲染答题控件（兼容其他页面）
    if (!setUserAnswer) {
        return <div>{renderPromptText()}</div>;
    }

    // ===== 答题控件部分 =====
    const renderInputArea = () => {
        // single_choice：选项左侧单选按钮，对应 ["A"]
        if (type === "single_choice" && front.options) {
            const ua = userAnswer;
            const current = ua[0] ?? "";

            return (
                <div className="mt-4 space-y-1 text-sm text-slate-100">
                    {front.options.map((opt, idx) => {
                        const code = indexToLetter(idx); // A/B/C...
                        const checked = current === code;

                        return (
                            <label
                                key={code}
                                className="flex items-center gap-2 cursor-pointer"
                            >
                                <input
                                    type="radio"
                                    name={`single-${front.prompt}`}
                                    className="h-4 w-4"
                                    checked={checked}
                                    onChange={() => {
                                        if (disabled) return;
                                        setUserAnswer([code]);
                                    }}
                                    disabled={disabled}
                                />
                                <span className="font-semibold">{code}.</span>
                                <span>{opt}</span>
                            </label>
                        );
                    })}
                </div>
            );
        }

        // multiple_choice：选项左侧复选框，对应 ["A","C"]
        if (type === "multiple_choice" && front.options) {
            const ua = userAnswer;

            return (
                <div className="mt-4 space-y-1 text-sm text-slate-100">
                    {front.options.map((opt, idx) => {
                        const code = indexToLetter(idx);
                        const checked = ua.includes(code);

                        const handleToggle = () => {
                            if (disabled) return;
                            let next: string[];
                            if (checked) {
                                next = ua.filter((c) => c !== code);
                            } else {
                                next = [...ua, code];
                            }
                            setUserAnswer(next);
                        };

                        return (
                            <label
                                key={code}
                                className="flex items-center gap-2 cursor-pointer"
                            >
                                <input
                                    type="checkbox"
                                    className="h-4 w-4"
                                    checked={checked}
                                    onChange={handleToggle}
                                    disabled={disabled}
                                />
                                <span className="font-semibold">{code}.</span>
                                <span>{opt}</span>
                            </label>
                        );
                    })}
                </div>
            );
        }

        // basic：简答题，对应 ["用户输入内容"]
        if (type === "basic") {
            const ua = userAnswer[0] ?? "";

            return (
                <textarea
                    className="mt-4 w-full rounded-md border border-slate-600 bg-slate-800/60 p-2 text-sm text-slate-100"
                    rows={3}
                    placeholder="在这里作答…"
                    value={ua}
                    onChange={(e) => {
                        if (disabled) return;
                        setUserAnswer([e.target.value]);
                    }}
                    disabled={disabled}
                />
            );
        }

        // fill_in_blank：填空题，对应 ["空1答案","空2答案",...]
        if (type === "fill_in_blank") {
            const blankCount = Math.max(1, countBlanks(front.prompt));
            const ua = userAnswer;

            return (
                <div className="mt-4 space-y-2 text-sm text-slate-100">
                    {Array.from({ length: blankCount }).map((_, idx) => (
                        <div key={idx} className="flex items-center gap-2">
                            <span className="text-xs text-slate-400">空{idx + 1}</span>
                            <input
                                className="flex-1 rounded-md border border-slate-600 bg-slate-800/60 px-2 py-1 text-sm"
                                value={ua[idx] ?? ""}
                                onChange={(e) => {
                                    if (disabled) return;
                                    const next = [...ua];
                                    next[idx] = e.target.value;
                                    setUserAnswer(next);
                                }}
                                disabled={disabled}
                            />
                        </div>
                    ))}
                </div>
            );
        }

        return null;
    };

    return (
        <div className="space-y-3">
            {renderPromptText()}
            {renderInputArea()}
        </div>
    );
}

/**
 * 渲染参考答案（back）
 * 与 UserAnswer 无关，只根据 BackSchema 展示
 */
export function renderAnswer(front: FrontSchema, back: BackSchema) {
    const slots = back.answers ?? [];
    const type = front.type;

    if (!slots.length) {
        return <span className="text-slate-400 text-sm">（未配置答案）</span>;
    }

    if (type === "basic") {
        const main = slots[0].join(" / ");
        return (
            <div className="space-y-2">
                <div className="text-sm text-emerald-200 whitespace-pre-wrap">
                    {main}
                </div>
                {back.explanation && (
                    <div className="text-xs text-slate-300 whitespace-pre-wrap">
                        {back.explanation}
                    </div>
                )}
            </div>
        );
    }

    if (type === "single_choice") {
        const codes = slots[0];
        return (
            <div className="space-y-2">
                <div className="text-sm text-emerald-200">
                    正确选项：{codes.join(" / ")}
                </div>
                {back.explanation && (
                    <div className="text-xs text-slate-300 whitespace-pre-wrap">
                        {back.explanation}
                    </div>
                )}
            </div>
        );
    }

    if (type === "multiple_choice") {
        const codes = slots.flat();
        return (
            <div className="space-y-2">
                <div className="text-sm text-emerald-200">
                    正确选项：{codes.join(", ")}
                </div>
                {back.explanation && (
                    <div className="text-xs text-slate-300 whitespace-pre-wrap">
                        {back.explanation}
                    </div>
                )}
            </div>
        );
    }

    if (type === "fill_in_blank") {
        return (
            <div className="space-y-2">
                <div className="space-y-1 text-sm text-emerald-200">
                    {slots.map((slot, idx) => (
                        <div key={idx}>
                            空{idx + 1}：{slot.join(" / ")}
                        </div>
                    ))}
                </div>
                {back.explanation && (
                    <div className="text-xs text-slate-300 whitespace-pre-wrap">
                        {back.explanation}
                    </div>
                )}
            </div>
        );
    }

    // 兜底
    return (
        <div className="text-sm text-emerald-200 whitespace-pre-wrap">
            {slots.flat().join(" / ")}
        </div>
    );
}

export interface QuizTemplate {
    id: string;
    title: string;
    description: string | null;
    item_ids: string [];
}
export interface QuizItemResult {
    /** 这道题对应的卡片 id（cards.id） */
    cardId: string;

    /** 这道题的分值（通常来自 front.score，默认 1 分） */
    score: number;

    /** 本次作答是否答对 */
    isCorrect: boolean;

    answer: UserAnswer | null;
}
export interface QuizRunResult {
    /** 测验开始时间 */
    startedAt: string;   // 建议用 ISO 字符串：new Date().toISOString()

    /** 测验结束时间 */
    finishedAt: string | null;

    /** 每道题的作答结果 */
    answers: QuizItemResult[];
}

export function renderFinishedArea(template: QuizTemplate,
                                   result: QuizRunResult | null,
                                   resultSaved: boolean) {
    if (!result) return null;

    const totalQuestions = result?.answers.length || 0;
    const correctCount = result?.answers.filter((it) => it.isCorrect).length;

    return (
        <div className="max-w-3xl mx-auto py-10 px-4">
            <div className="mb-6 flex items-center gap-3">
                <BookOpen className="w-7 h-7 text-emerald-400"/>
                <div>
                    <div className="text-xl font-semibold text-white">
                        {template.title}
                    </div>
                    <div className="text-xs text-slate-400 mt-1">测验完成 ✅</div>
                </div>
            </div>

            <div className="rounded-2xl border border-slate-700 bg-slate-900/70 p-6 text-slate-100">
                <div className="text-lg mb-3">
                    正确题数：{" "}
                    <span className="font-semibold text-emerald-400">
              {correctCount}
            </span>{" "}
                    / {totalQuestions}
                </div>
                <div className="text-sm text-slate-400 mb-6">
                    正确率{" "}
                    <span className="font-semibold text-sky-400">
              {Math.round((correctCount / totalQuestions) * 100)}%
            </span>
                </div>

                {/* 这里根据 hasSaved 来决定是否显示按钮 / 提示文案 */}
                {!resultSaved && (
                    <div className="text-xs text-slate-500">
                        正在保存测验结果，请稍候…
                    </div>
                )}

                {resultSaved && (
                    <div className="flex flex-wrap gap-3 mt-4">
                        <Link
                            to="/quizzes"
                            className="px-5 py-2.5 rounded-2xl border border-slate-500 text-slate-200 text-sm hover:bg-slate-800 inline-flex items-center justify-center"
                        >
                            返回测验列表
                        </Link>
                    </div>
                )}
            </div>
        </div>
    );
}