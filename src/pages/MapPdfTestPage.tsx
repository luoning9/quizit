import React, { useState } from "react";
import { MapPdfViewer } from "../components/ui/MapPdfViewer.tsx";
import { Button } from "../components/ui/Button.tsx";

/**
 * 内部调试页：用于验证 MapPdfViewer（react-pdf 方案）是否能正确加载 Supabase 私有链接。
 * 通过输入 cardId 与 .map 文件名，读取存储的地图配置并预览单页 PDF。
 */
export default function MapPdfTestPage() {
    const [cardId, setCardId] = useState("");
    const [fileName, setFileName] = useState("");
    const [submittedCardId, setSubmittedCardId] = useState<string | null>(null);
    const [submittedFileName, setSubmittedFileName] = useState<string | null>(null);

    function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        if (!cardId.trim() || !fileName.trim()) return;
        setSubmittedCardId(cardId.trim());
        setSubmittedFileName(fileName.trim());
    }

    return (
        <div className="space-y-4">
            <div>
                <div className="text-lg font-semibold">MapPdfViewer 调试页</div>
                <p className="text-sm text-slate-600 dark:text-slate-300">
                    填入 cardId 与存储中的 .map 文件名，将自动从 Supabase Storage 读取配置并展示 PDF。
                </p>
            </div>

            <form
                onSubmit={handleSubmit}
                className="space-y-3 p-4 rounded-xl border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900/40"
            >
                <label className="block text-sm font-medium mb-1">
                    cardId
                </label>
                <input
                    type="text"
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 dark:bg-slate-900 dark:border-slate-700 dark:text-slate-100 dark:focus:border-sky-500 dark:focus:ring-sky-300/30"
                    placeholder="如 abcd-1234"
                    value={cardId}
                    onChange={(e) => setCardId(e.target.value)}
                    required
                />

                <label className="block text-sm font-medium mb-1">
                    .map 文件名
                </label>
                <input
                    type="text"
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 dark:bg-slate-900 dark:border-slate-700 dark:text-slate-100 dark:focus:border-sky-500 dark:focus:ring-sky-300/30"
                    placeholder="例如 map/region1.map"
                    value={fileName}
                    onChange={(e) => setFileName(e.target.value)}
                    required
                />

                <div className="pt-2">
                    <Button type="submit" className="px-4 py-2">
                        预览
                    </Button>
                </div>
            </form>

            {submittedCardId && submittedFileName ? (
                <MapPdfViewer
                    cardId={submittedCardId}
                    filename={submittedFileName}
                />
            ) : (
                <div className="text-sm text-slate-500 dark:text-slate-400">
                    填写 cardId 和 .map 文件名后点击预览，支持缩放、旋转、重置。
                </div>
            )}
        </div>
    );
}
