// src/features/decks/NewDeckPage.tsx
import React, { useState } from "react";
import {useNavigate, useSearchParams} from "react-router-dom";
import { supabase } from "../../lib/supabaseClient";
import { Button } from "../components/ui/Button";

const NewDeckPage: React.FC = () => {
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
                    owner_id: user.id,
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
        <div className="max-w-2xl mx-auto px-4 py-6 text-slate-100 space-y-6">
            {/* 顶部标题 */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-xl font-semibold">新建 Deck</h1>
                    <p className="text-xs text-slate-400 mt-1">
                        只需填写标题和简介，创建后可以在编辑页添加卡片。
                    </p>
                </div>

                <Button
                    type="button"
                    variant="link"
                    className="text-xs px-0 text-sky-400 hover:text-sky-300 underline underline-offset-4"
                    onClick={() => navigate(-1)}
                >
                    返回
                </Button>
            </div>

            {/* 错误提示 */}
            {error && (
                <div className="text-sm text-rose-400 border border-rose-500/50 bg-rose-950/40 rounded-xl px-3 py-2">
                    {error}
                </div>
            )}

            {/* 表单 */}
            <form
                onSubmit={handleSubmit}
                className="rounded-2xl border border-slate-700 bg-slate-900/70 p-4 space-y-4"
            >
                <div className="space-y-1.5">
                    <label className="block text-sm text-slate-200">
                        标题 <span className="text-rose-400">*</span>
                    </label>
                    <input
                        type="text"
                        className="w-full rounded-xl bg-slate-950/70 border border-slate-700 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500"
                        placeholder="例如：physics/八年级/声现象基础卡片"
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                    />
                </div>

                <div className="space-y-1.5">
                    <label className="block text-sm text-slate-200">简介（可选）</label>
                    <textarea
                        className="w-full h-24 rounded-xl bg-slate-950/70 border border-slate-700 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500 resize-none"
                        placeholder="简单描述这个 deck 的内容和用途。"
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                    />
                </div>

                <div className="pt-2 flex justify-end">
                    <Button
                        type="submit"
                        variant="primary"
                        disabled={submitting || !title.trim()}
                        className="text-sm font-medium px-4 py-2 rounded-xl"
                    >
                        {submitting ? "创建中…" : "创建 Deck"}
                    </Button>
                </div>
            </form>
        </div>
    );
};

export default NewDeckPage;
