import React, { useState } from "react";
import { MapPdfViewer } from "../components/ui/MapPdfViewer.tsx";
import { Button } from "../components/ui/Button.tsx";

/**
 * 内部调试页：用于验证 MapPdfViewer（react-pdf 方案）是否能正确加载 Supabase 私有链接。
 * 通过输入签名 URL 和可选 Bearer token，预览单页 PDF。
 */
export default function MapPdfTestPage() {
    const [pdfUrl, setPdfUrl] = useState("");
    const [authToken, setAuthToken] = useState("");
    const [page, setPage] = useState(1);
    const [submittedUrl, setSubmittedUrl] = useState<string | null>(null);
    const [submittedToken, setSubmittedToken] = useState<string | undefined>();
    const [submittedPage, setSubmittedPage] = useState<number>(1);

    function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        if (!pdfUrl.trim()) return;
        setSubmittedUrl(pdfUrl.trim());
        setSubmittedToken(authToken.trim() ? authToken.trim() : undefined);
        setSubmittedPage(page > 0 ? page : 1);
    }

    return (
        <div className="space-y-4">
            <div>
                <div className="text-lg font-semibold">MapPdfViewer 调试页</div>
                <p className="text-sm text-slate-600 dark:text-slate-300">
                    填入单页 PDF 的签名链接（Supabase Storage）和可选 Bearer token，点击预览。
                </p>
            </div>

            <form
                onSubmit={handleSubmit}
                className="space-y-3 p-4 rounded-xl border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900/40"
            >
                <label className="block text-sm font-medium mb-1">
                    PDF 链接（签名 URL）
                </label>
                <input
                    type="url"
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 dark:bg-slate-900 dark:border-slate-700 dark:text-slate-100 dark:focus:border-sky-500 dark:focus:ring-sky-300/30"
                    placeholder="https://xxx.supabase.co/storage/v1/object/sign/bucket/path/page1.pdf?token=..."
                    value={pdfUrl}
                    onChange={(e) => setPdfUrl(e.target.value)}
                    required
                />

                <label className="block text-sm font-medium mb-1">
                    Bearer Token（可选，若签名 URL 已含 token 可留空）
                </label>
                <input
                    type="text"
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 dark:bg-slate-900 dark:border-slate-700 dark:text-slate-100 dark:focus:border-sky-500 dark:focus:ring-sky-300/30"
                    placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
                    value={authToken}
                    onChange={(e) => setAuthToken(e.target.value)}
                />

                <label className="block text-sm font-medium mb-1">
                    页码（默认 1）
                </label>
                <input
                    type="number"
                    min={1}
                    className="w-28 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 dark:bg-slate-900 dark:border-slate-700 dark:text-slate-100 dark:focus:border-sky-500 dark:focus:ring-sky-300/30"
                    value={page}
                    onChange={(e) => setPage(Number(e.target.value))}
                />

                <div className="pt-2">
                    <Button type="submit" className="px-4 py-2">
                        预览
                    </Button>
                </div>
            </form>

            {submittedUrl ? (
                <MapPdfViewer
                    pdfUrl={submittedUrl}
                    authToken={submittedToken}
                    pageNumber={submittedPage}
                    title="单页 PDF 预览"
                />
            ) : (
                <div className="text-sm text-slate-500 dark:text-slate-400">
                    填写链接后点击预览，支持缩放、旋转、重置。
                </div>
            )}
        </div>
    );
}
