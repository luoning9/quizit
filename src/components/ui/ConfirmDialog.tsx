// src/components/ui/ConfirmDialog.tsx
import React from "react";
import { Button } from "./Button.tsx";

interface ConfirmDialogProps {
    open: boolean;
    title?: string;
    description?: string;
    confirmLabel?: string;
    cancelLabel?: string;
    loading?: boolean;
    onConfirm: () => void;
    onCancel: () => void;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
                                                                open,
                                                                title = "确认操作",
                                                                description,
                                                                confirmLabel = "确认",
                                                                cancelLabel = "取消",
                                                                loading = false,
                                                                onConfirm,
                                                                onCancel,
                                                            }) => {
    if (!open) return null;

    return (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60">
            <div className="w-full max-w-sm rounded-2xl bg-slate-900 border border-slate-700 p-4 shadow-xl">
                <div className="text-sm font-semibold text-slate-100 mb-2">
                    {title}
                </div>
                {description && (
                    <div className="text-xs text-slate-300 mb-4 whitespace-pre-wrap">
                        {description}
                    </div>
                )}
                <div className="flex justify-end gap-2">
                    <Button
                        type="button"
                        variant="outline"
                        className="px-3 py-1.5 text-xs border-slate-600 text-slate-300 hover:bg-slate-800"
                        onClick={onCancel}
                        disabled={loading}
                    >
                        {cancelLabel}
                    </Button>
                    <Button
                        type="button"
                        variant="primary"
                        className="px-3 py-1.5 text-xs bg-rose-600 border-rose-500 hover:bg-rose-500 text-white"
                        onClick={onConfirm}
                        disabled={loading}
                    >
                        {loading ? "执行中…" : confirmLabel}
                    </Button>
                </div>
            </div>
        </div>
    );
};