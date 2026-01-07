// src/features/decks/DeckCreatePage.tsx
import React, { useState } from "react";
import {useNavigate, useSearchParams} from "react-router-dom";
import { supabase } from "../../lib/supabaseClient";
import { Button } from "../components/ui/Button";
import { Layers, CornerUpLeft } from "lucide-react";

const DeckCreatePage: React.FC = () => {
    const [searchParams] = useSearchParams();
    // 用 URL 里的 ?path=... 作为初始值，没有就用 "/"
    const initialPath = searchParams.get("path") || "";

    const navigate = useNavigate();

    const [title, setTitle] = useState(initialPath?initialPath+'/':"");
    const [description, setDescription] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        if (!title.trim()) {
            setError("标题不能为空。");
            return;
        }

        setError(null);
        setSubmitting(true);

        try {
            // 1. 获取当前用户
            const {
                data: { user },
                error: userError,
            } = await supabase.auth.getUser();

            if (userError || !user) {
                console.error("getUser error", userError);
                setError("请先登录再创建 deck。");
                setSubmitting(false);
                return;
            }

            // 2. 插入 decks
            const { data, error: insertError } = await supabase
                .from("decks")
                .insert({
                    title: title.trim(),
                    description: description.trim() || null,
                    // 其它字段用默认值：items 默认为 {"items": []}
                })
                .select("id")
                .single();

            if (insertError || !data) {
                console.error("insert deck error", insertError);
                setError("创建 deck 失败，请稍后再试。");
                setSubmitting(false);
                return;
            }

            // 3. 跳转到编辑页面
            navigate(`/decks/${data.id}/edit`);
        } catch (err) {
            console.error(err);
            setError("发生未知错误。");
            setSubmitting(false);
        }
    }

    return (
        <div className="max-w-2xl mx-auto px-4 py-6 space-y-6 text-slate-900 dark:text-slate-100">
            {/* 顶部标题 */}
            <div className="flex items-center justify-between">
                <div>
                    <div className="flex items-center gap-3">
                        <Layers className="w-8 h-8 text-emerald-600 dark:text-sky-300" />
                        <div>
                            <h1 className="text-xl font-semibold">新建 Deck</h1>
                            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                                只需填写标题和简介，创建后可以在编辑页添加卡片。
                            </p>
                        </div>
                    </div>
                </div>

                <Button
                    type="button"
                    variant="iconRound"
                    className="text-emerald-600 hover:text-white hover:bg-emerald-600 dark:text-sky-300 dark:hover:text-sky-100 dark:hover:bg-sky-700"
                    onClick={() => navigate(-1)}
                    title="返回"
                >
                    <CornerUpLeft className="w-6 h-6" />
                </Button>
            </div>

            {/* 错误提示 */}
            {error && (
                <div className="text-sm text-rose-600 border border-rose-200 bg-rose-50 rounded-xl px-3 py-2 dark:text-rose-400 dark:border-rose-500/50 dark:bg-rose-950/40">
                    {error}
                </div>
            )}

            {/* 表单 */}
            <form
                onSubmit={handleSubmit}
                className="rounded-2xl border border-slate-200 bg-white/90 p-4 space-y-4 shadow-sm dark:border-slate-700 dark:bg-slate-900/70"
            >
                <div className="space-y-1.5">
                    <label className="block text-sm text-slate-700 dark:text-slate-200">
                        标题 <span className="text-rose-500">*</span>
                    </label>
                    <input
                        type="text"
                        className="w-full rounded-xl bg-white border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 dark:bg-slate-950/70 dark:border-slate-700 dark:text-slate-100 dark:focus:border-sky-500 dark:focus:ring-sky-300/30"
                        placeholder="例如：physics/八年级/声现象基础卡片"
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                    />
                </div>

                <div className="space-y-1.5">
                    <label className="block text-sm text-slate-700 dark:text-slate-200">简介（可选）</label>
                    <textarea
                        className="w-full h-24 rounded-xl bg-white border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 resize-none dark:bg-slate-950/70 dark:border-slate-700 dark:text-slate-100 dark:focus:border-sky-500 dark:focus:ring-sky-300/30"
                        placeholder="简单描述这个 deck 的内容和用途。"
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                    />
                </div>

                <div className="pt-2 flex justify-end">
                    <Button
                        type="submit"
                        variant="primary"
                        disabled={
                            submitting ||
                            !title.trim() ||
                            title.trim() === initialPath.trim() ||
                            title.trim().endsWith("/")
                        }
                        className="text-sm font-medium px-4 py-2 rounded-xl"
                    >
                        {submitting ? "创建中…" : "创建 Deck"}
                    </Button>
                </div>
            </form>
        </div>
    );
};

export default DeckCreatePage;
