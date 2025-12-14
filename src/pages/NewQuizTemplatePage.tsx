import React, {useMemo, useState, type Dispatch, type SetStateAction} from "react";
import {useNavigate, useSearchParams} from "react-router-dom";
import {supabase} from "../../lib/supabaseClient";
import {Button} from "../components/ui/Button";
import {List, PencilLine} from "lucide-react";
import {Loader2} from "lucide-react";

type Mode = "mixed";
type QuestionType = "single" | "multiple" | "fill_in_blank" | "basic";

interface DraftItem {
    front: string;
    back: string;
    score: number;
}

const SAMPLE_JSON = `{
  "items": [
    { "front": "声音是由什么产生的？", "back": "由物体振动产生。", "score": 1 },
    { "front": "声音在真空中能传播吗？", "back": "不能。", "score": 1 }
  ]
}`;

interface AiDialogProps {
    open: boolean;
    prompt: string;
    setPrompt: (v: string) => void;
    count: number;
    setCount: (v: number) => void;
    difficulty: "easy" | "medium" | "hard";
    setDifficulty: (v: "easy" | "medium" | "hard") => void;
    questionTypes: QuestionType[];
    setQuestionTypes: Dispatch<SetStateAction<QuestionType[]>>;
    path: string;
    onGenerate: () => void;
    onClose: () => void;
    loading?: boolean;
}

function AiDialog({
                      open,
                      prompt,
                      setPrompt,
                      count,
                      setCount,
                      difficulty,
                      setDifficulty,
                      questionTypes,
                      setQuestionTypes,
                      path,
                      onGenerate,
                      onClose,
                      loading,
                  }: AiDialogProps) {
    if (!open) return null;

    return (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60">
            <div
                className="w-full max-w-3xl rounded-2xl bg-white p-5 shadow-xl dark:bg-slate-900 dark:border dark:border-slate-700">
                <div className="flex items-center justify-between mb-3">
                    <div className="text-base font-semibold text-slate-900 dark:text-slate-100">
                        AI 生成
                    </div>
                    <Button
                        type="button"
                        variant="ghost"
                        className="text-sm"
                        onClick={onClose}
                        disabled={loading}
                    >
                        关闭
                    </Button>
                </div>

                <div className="space-y-3">
                    <div>
                        <label className="text-sm text-slate-700 dark:text-slate-200">
                            提示词
                        </label>
                        <textarea
                            className="mt-1 w-full h-20 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 dark:bg-slate-950/70 dark:border-slate-700 dark:text-slate-100 dark:focus:border-sky-500 dark:focus:ring-sky-300/30"
                            value={prompt}
                            onChange={(e) => setPrompt(e.target.value)}
                            placeholder="例如：生成一道关于力和运动的选择题"
                        />
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-6">
                        <div>
                            <div className="text-sm text-slate-700 dark:text-slate-200 mb-1">
                                题目数量：<span
                                className="font-semibold text-emerald-700 dark:text-emerald-300">{count}</span>
                            </div>
                            <input
                                type="range"
                                min={1}
                                max={25}
                                step={1}
                                value={count}
                                onChange={(e) => setCount(Number(e.target.value))}
                                className="w-full accent-blue-500 h-1.5 rounded-full bg-blue-100"
                                disabled={loading}
                            />
                        </div>

                        <div>
                            <div className="text-sm text-slate-700 dark:text-slate-200 mb-1">
                                难度
                            </div>
                            <div className="flex items-center gap-4 text-lg text-slate-700 dark:text-slate-200">
                                {[
                                    {label: "易", value: "easy"},
                                    {label: "中", value: "medium"},
                                    {label: "难", value: "hard"},
                                ].map((opt) => (
                                    <label key={opt.value} className="flex items-center gap-1 cursor-pointer">
                                        <input
                                            type="radio"
                                            name="ai-difficulty"
                                            value={opt.value}
                                            checked={difficulty === opt.value}
                                            onChange={() => setDifficulty(opt.value as "easy" | "medium" | "hard")}
                                            disabled={loading}
                                        />
                                        <span>{opt.label}</span>
                                    </label>
                                ))}
                            </div>
                        </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-6 items-start">
                        <div>
                            <div className="text-sm text-slate-700 dark:text-slate-200 mb-1">
                                题型（可多选）
                            </div>
                            <div className="flex flex-wrap gap-3">
                                {[
                                    {label: "单选", value: "single"},
                                    {label: "多选", value: "multiple"},
                                    {label: "填空", value: "fill_in_blank"},
                                    {label: "简答", value: "basic"},
                                ].map((opt) => {
                                    const checked = questionTypes.includes(opt.value as QuestionType);
                                    return (
                                        <label
                                            key={opt.value}
                                            className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm bg-white text-slate-700 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 cursor-pointer"
                                            style={{outline: "none"}}
                                        >
                                            <input
                                                type="checkbox"
                                                className="h-4 w-4"
                                                checked={checked}
                                                disabled={loading}
                                                onChange={(e) => {
                                                    setQuestionTypes((prev) => {
                                                        const set = new Set(prev);
                                                        if (e.target.checked) {
                                                            set.add(opt.value as QuestionType);
                                                        } else {
                                                            set.delete(opt.value as QuestionType);
                                                        }
                                                        return Array.from(set) as QuestionType[];
                                                    });
                                                }}
                                            />
                                            <span>{opt.label}</span>
                                        </label>
                                    );
                                })}
                            </div>
                        </div>
                        <div>
                            <div className="text-sm text-slate-700 dark:text-slate-200 mb-1">
                                测验内容
                            </div>
                            <input
                                type="text"
                                value={path}
                                readOnly
                                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 dark:bg-slate-800 dark:border-slate-600 dark:text-slate-200"
                            />
                        </div>
                    </div>

                    <div className="flex justify-end gap-2 pt-2">
                        <Button
                            type="button"
                            variant="ghost"
                            onClick={onClose}
                            disabled={loading}
                            className="text-sm"
                        >
                            取消
                        </Button>
                        <Button
                            type="button"
                            variant="primary"
                            onClick={onGenerate}
                            disabled={loading}
                            className="text-sm"
                        >
                            {loading ? "生成中…" : "生成"}
                        </Button>
                    </div>
                </div>
            </div>
        </div>
    );
}

/**
 * 在 JSON.parse 之前仅对数学公式外的特殊转义做加倍，避免 \t \n 被吞掉，
 * 同时保留 $...$ 内的 LaTeX 反斜杠。
 */
function normalizeEscapesOutsideMath(text: string): string {
    let inMath = false;
    let result = "";

    for (let i = 0; i < text.length; i++) {
        const ch = text[i];

        if (ch === "$") {
            inMath = !inMath; // 简单切换，假定成对出现
            result += ch;
            continue;
        }

        // 只有在数学片段内，才加倍单反斜杠 + 特定转义字符，保护 \text 等
        if (inMath && ch === "\\" && i + 1 < text.length) {
            const next = text[i + 1];
            if (/[btnrfu]/.test(next)) {
                result += "\\\\" + next;
                i++; // 跳过 next
                continue;
            }
        }

        result += ch;
    }

    return result;
}

function parseItems(text: string): DraftItem[] {
    try {
        const normalized = normalizeEscapesOutsideMath(text);
        const parsed = JSON.parse(normalized);
        const arr: unknown = Array.isArray(parsed?.items) ? parsed.items : parsed;
        if (!Array.isArray(arr)) return [];

        return arr
            .map((it: any) => ({
                front:
                    typeof it.front === "string"
                        ? it.front
                        : it.front
                            ? JSON.stringify(it.front)
                            : "",
                back:
                    typeof it.back === "string"
                        ? it.back
                        : it.back
                            ? JSON.stringify(it.back)
                            : "",
                score:
                    typeof it.score === "number" && it.score > 0
                        ? it.score
                        : typeof it.score === "string" && !Number.isNaN(Number(it.score))
                            ? Number(it.score) || 1
                            : 1,
            }))
            .filter((it) => it.front.trim().length > 0 || it.back.trim().length > 0);
    } catch {
        return [];
    }
}

export default function NewQuizTemplatePage() {
    const [searchParams] = useSearchParams();
    const path = searchParams.get("path") || "";
    const deckName = searchParams.has("is_deck") ? path.split("/").slice(0, -1).join("/") : path;
    const navigate = useNavigate();

    const [title, setTitle] = useState(path ? `${path.split("/").filter(Boolean).pop() ?? ""} 测验` : "");
    const [description, setDescription] = useState("");
    const [mode] = useState<Mode>("mixed");
    const [itemsText, setItemsText] = useState("");
    const [hasTypedItems, setHasTypedItems] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);

    const [aiOpen, setAiOpen] = useState(false);
    const [aiPrompt, setAiPrompt] = useState("");
    const [aiCount, setAiCount] = useState<number>(10);
    const [aiDifficulty, setAiDifficulty] = useState<"easy" | "medium" | "hard">("medium");
    const [aiQuestionTypes, setAiQuestionTypes] = useState<QuestionType[]>(["single"]);
    const [aiLoading, setAiLoading] = useState(false);

    const parsedItems = useMemo(() => parseItems(itemsText), [itemsText]);

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        setError(null);

        const trimmedTitle = title.trim();
        if (!trimmedTitle) {
            setError("标题不能为空");
            return;
        }

        const items = parseItems(itemsText);
        if (!items.length) {
            setError("请提供至少一条题目（front/back/score）。");
            return;
        }

        setSaving(true);

        try {
            const {
                data: {user},
                error: userError,
            } = await supabase.auth.getUser();

            if (userError || !user) {
                setError("请先登录。");
                setSaving(false);
                return;
            }

            const insertPayload = items.map((it) => ({
                front: it.front,
                back: it.back,
                card_type: "basic" as const,
            }));

            const {data: insertedCards, error: insertError} = await supabase
                .from("cards")
                .insert(insertPayload)
                .select("id, front, back");

            if (insertError || !insertedCards || insertedCards.length === 0) {
                console.error("insert cards error", insertError);
                setError("创建卡片失败。");
                setSaving(false);
                return;
            }

            const itemsForTemplate = insertedCards.map((c, idx) => ({
                card_id: c.id,
                position: idx + 1,
                score: items[idx]?.score ?? 1,
            }));

            const config = {
                source_path: path,
                question_count: itemsForTemplate.length,
                shuffle: true,
                created_from: "manual",
            };

            const {data: tmpl, error: tmplError} = await supabase
                .from("quizzes")
                .insert({
                    title: trimmedTitle,
                    description: description.trim() || null,
                    deck_name: deckName || null,
                    mode,
                    items: {items: itemsForTemplate},
                    config,
                })
                .select("id")
                .single();

            if (tmplError || !tmpl) {
                console.error("insert quiz error", tmplError);
                setError("创建测验失败。");
                setSaving(false);
                return;
            }

            navigate(`/quizzes/${tmpl.id}/take`);
        } catch (err) {
            console.error(err);
            setError("出现未知错误。");
            setSaving(false);
        }
    }

    async function handleAiGenerate() {
        setAiLoading(true);
        setAiOpen(false);
        const countNum = Number(aiCount);
        const prompt = aiPrompt.trim() || "请根据卡片内容生成题目";
        const types = aiQuestionTypes.length ? aiQuestionTypes : (["single"] as string[]);

        try {
            // 先获取卡片内容
            const {data: cards, error: cardsError} = await supabase.rpc("select_cards_by_path", {
                _path: path,
                _limit: countNum * 3,
                _mode: "random",
            });

            if (cardsError || !Array.isArray(cards) || cards.length === 0) {
                console.error("select_cards_by_path error", cardsError);
                setError("未能获取学习路径下的卡片，无法生成题目");
                setAiLoading(false);
                return;
            }

            const payloadCards = cards
                .map((row: any) => ({
                    front: String(row.front ?? "").trim(),
                    back: String(row.back ?? "").trim(),
                }))
                .filter((row) => row.front || row.back);
            console.log(payloadCards);

            const {data, error} = await supabase.functions.invoke("gen-questions", {
                body: {
                    count: countNum,
                    prompt,
                    questionTypes: types,
                    cards: payloadCards,
                },
            });

            if (error) {
                console.error("gen-questions error", error);
                setError("AI 生成失败，请稍后再试");
            } else if (data) {
                const content = typeof data === "string" ? data : JSON.stringify(data, null, 2);
                setItemsText(content);
            }
        } catch (err) {
            console.error("invoke gen-questions error", err);
            setError("AI 生成异常，请稍后再试");
        } finally {
            setAiLoading(false);
        }
    }

    return (
        <div className="max-w-4xl mx-auto px-4 py-6 space-y-6 text-slate-900 dark:text-slate-100">
            <div className="flex items-center justify-between">
                <div>
                    <div className="flex items-center gap-3">
                        <PencilLine className="w-6 h-6 text-emerald-600 dark:text-sky-300"/>
                        <div>
                            <h1 className="text-xl font-semibold">新建测验</h1>
                            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                                输入题目内容（front/back），系统会为每题创建卡片并生成测验模板。
                            </p>
                        </div>
                    </div>
                </div>
                <Button
                    variant="link"
                    className="p-3 rounded-full text-emerald-600 hover:text-white hover:bg-emerald-600 dark:text-sky-300 dark:hover:text-sky-100 dark:hover:bg-sky-700"
                    onClick={() => navigate(-1)}
                    title="返回"
                >
                    <List className="w-6 h-6"/>
                </Button>
            </div>

            {error && (
                <div
                    className="text-sm text-rose-600 border border-rose-200 bg-rose-50 rounded-xl px-3 py-2 dark:text-rose-400 dark:border-rose-500/50 dark:bg-rose-950/40">
                    {error}
                </div>
            )}

            <form
                onSubmit={handleSubmit}
                className="rounded-2xl border border-slate-200 bg-white/90 p-4 space-y-4 shadow-sm dark:border-slate-700 dark:bg-slate-900/70"
            >
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-center">
                    <div className="flex items-center gap-2 whitespace-nowrap">
                        <label className="text-sm text-slate-700 dark:text-slate-200 whitespace-nowrap">
                            标题 <span className="text-rose-500">*</span>
                        </label>
                        <label className="bg-slate-800">{`${deckName}/`}</label>
                        <input
                            type="text"
                            className="w-full rounded-xl bg-white border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 dark:bg-slate-950/70 dark:border-slate-700 dark:text-slate-100 dark:focus:border-sky-500 dark:focus:ring-sky-300/30"
                            value={title}
                            onChange={(e) => setTitle(e.target.value)}
                            placeholder="例如：七年级生物测验"
                        />
                    </div>
                    <div className="flex items-center gap-2">
                        <label className="text-sm text-slate-700 dark:text-slate-200 whitespace-nowrap">
                            描述
                        </label>
                        <input
                            type="text"
                            className="w-full rounded-xl bg-white border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 dark:bg-slate-950/70 dark:border-slate-700 dark:text-slate-100 dark:focus:border-sky-500 dark:focus:ring-sky-300/30"
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            placeholder="简单描述这个测验的目的或范围。"
                        />
                    </div>
                </div>

                <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold">题目内容（JSON）</div>
                    <div className="flex items-center gap-2">
                        {aiLoading && <Loader2 className="h-8 w-8 animate-spin text-emerald-500"/>}
                        <Button
                            variant="outline"
                            type="button"
                            className="text-sm"
                            onClick={() => setAiOpen(true)}
                            disabled={aiLoading || !path}
                        >
                            AI 生成…
                        </Button>
                    </div>
                </div>

                <textarea
                    className="w-full h-60 text-xs font-mono bg-white border border-slate-300 rounded-xl p-3 text-slate-900 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 dark:bg-slate-950/80 dark:border-slate-700 dark:text-slate-100"
                    value={itemsText}
                    onChange={(e) => {
                        const val = e.target.value;
                        if (!hasTypedItems && val !== SAMPLE_JSON) {
                            setHasTypedItems(true);
                        }
                        setItemsText(val);
                    }}
                    placeholder={SAMPLE_JSON}
                    onFocus={() => {
                        if (!hasTypedItems && itemsText === SAMPLE_JSON) {
                            setItemsText("");
                        }
                    }}
                />

                <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                    <span>已解析题目：{parsedItems.length} 条</span>
                    <span>模式：混合</span>
                </div>

                <div className="flex justify-end">
                    <Button
                        type="submit"
                        variant="primary"
                        disabled={saving || aiLoading || !title.trim()}
                        className="text-sm px-4 py-2"
                    >
                        {saving || aiLoading ? "创建中…" : "创建测验"}
                    </Button>
                </div>
            </form>

            <AiDialog
                open={aiOpen}
                prompt={aiPrompt}
                setPrompt={setAiPrompt}
                count={aiCount}
                setCount={setAiCount}
                difficulty={aiDifficulty}
                setDifficulty={setAiDifficulty}
                questionTypes={aiQuestionTypes}
                setQuestionTypes={setAiQuestionTypes}
                path={path}
                onGenerate={handleAiGenerate}
                onClose={() => setAiOpen(false)}
                loading={aiLoading}
            />
        </div>
    );
}
