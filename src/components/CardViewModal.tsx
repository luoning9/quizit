import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { GitBranch, Image as ImageIcon, Map as MapIcon, X } from "lucide-react";
import { supabase } from "../../lib/supabaseClient";
import { parseBack, parseFront, type UserAnswer } from "../../lib/quizFormat";
import { renderAnswer, renderPrompt } from "../pages/quizRenderer";
import MarkdownText from "./MarkdownText";
import { Button } from "./ui/Button";
import { DotRender } from "./ui/DotRender";
import { ImageRender } from "./ui/ImageRender";
import { MapPdfViewer } from "./ui/MapPdfViewer";

type CardViewRow = {
    id: string;
    front: string;
    back: string;
};

type MediaFile = {
    name: string;
    id?: string;
};

type MediaModal = {
    cardId: string;
    name: string;
};

function trimEmptyLines(content: string): string {
    const lines = content.split(/\r?\n/);
    while (lines.length && !lines[0].trim()) lines.shift();
    while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
    return lines.join("\n");
}

function getMediaType(name: string): "dot" | "map" | "image" | null {
    const lower = name.toLowerCase();
    if (lower.endsWith(".dot")) return "dot";
    if (lower.endsWith(".map")) return "map";
    if (/\.(png|jpe?g)$/.test(lower)) return "image";
    return null;
}

function extractNotesFromContent(text?: string): string[] {
    const notes: string[] = [];
    if (!text) return notes;
    const regex = /!\[([^\]]*)]/g;
    let match;
    while ((match = regex.exec(text)) !== null) {
        notes.push(match[1]?.trim() ?? "");
    }
    return notes;
}

function MediaButton({
    cardId,
    name,
    note,
    onOpen,
}: {
    cardId: string;
    name: string;
    note?: string;
    onOpen: (media: MediaModal) => void;
}) {
    const mediaType = getMediaType(name);
    if (!mediaType) return null;

    const Icon = mediaType === "dot" ? GitBranch : mediaType === "map" ? MapIcon : ImageIcon;

    return (
        <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-blue-700 shadow-sm hover:bg-blue-50 dark:border-slate-700 dark:bg-slate-950 dark:text-blue-300 dark:hover:bg-slate-800"
            onClick={() => onOpen({ cardId, name })}
            title={note || `查看媒体 (${name})`}
        >
            <Icon
                className={clsx(
                    "h-4 w-4",
                    mediaType === "dot"
                        ? "text-emerald-500"
                        : mediaType === "map"
                            ? "text-sky-500"
                            : "text-blue-500"
                )}
                aria-hidden="true"
            />
            <span>{note || name}</span>
        </button>
    );
}

export function CardViewModal({
    card,
    onClose,
}: {
    card: CardViewRow | null;
    onClose: () => void;
}) {
    const [mediaFiles, setMediaFiles] = useState<MediaFile[]>([]);
    const [mediaLoading, setMediaLoading] = useState(false);
    const [mediaModal, setMediaModal] = useState<MediaModal | null>(null);

    const view = useMemo(() => {
        if (!card) return null;
        const frontClean = trimEmptyLines(card.front);
        const backClean = trimEmptyLines(card.back);
        const backSchema = parseBack(card.back, true);
        const footerText = backSchema?.footer ?? "";
        const backNotes = extractNotesFromContent(footerText);
        const frontMediaNames = mediaFiles.filter((file) => file.name.startsWith("front.")).map((file) => file.name);
        const backMediaNames = mediaFiles.filter((file) => file.name.startsWith("back")).map((file) => file.name);
        const mediaNotes: Record<string, string> = {};

        backMediaNames.forEach((name, index) => {
            const lower = name.toLowerCase();
            if (lower.endsWith(".png") || lower.endsWith(".jpg") || lower.endsWith(".jpeg")) {
                mediaNotes[name] = backNotes[index] ?? "";
            }
        });

        return {
            frontClean,
            backClean,
            frontSchema: parseFront(card.front),
            backSchema,
            footerText,
            frontMediaNames,
            backMediaNames,
            mediaNotes,
        };
    }, [card, mediaFiles]);

    useEffect(() => {
        let cancelled = false;

        async function loadMediaFiles() {
            if (!card) {
                setMediaFiles([]);
                setMediaModal(null);
                return;
            }

            setMediaLoading(true);
            try {
                const { data, error } = await supabase.storage
                    .from("quizit_card_medias")
                    .list(card.id);

                if (cancelled) return;

                if (error || !data) {
                    console.error("load card media error", error);
                    setMediaFiles([]);
                    return;
                }

                setMediaFiles((data as MediaFile[]).map((file) => ({ name: file.name, id: file.id })));
            } finally {
                if (!cancelled) setMediaLoading(false);
            }
        }

        void loadMediaFiles();
        return () => {
            cancelled = true;
        };
    }, [card]);

    if (!card || !view) return null;

    const footerForRender = view.footerText.trim();

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4 backdrop-blur-sm"
            onClick={onClose}
        >
            <div
                className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-950"
                onClick={(event) => event.stopPropagation()}
            >
                <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
                    <div className="min-w-0">
                        <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">查看闪卡</div>
                        <div className="truncate text-xs text-slate-500 dark:text-slate-400">{card.id}</div>
                    </div>
                    <Button
                        type="button"
                        variant="iconGhost"
                        className="h-9 w-9 rounded-lg p-0 text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                        aria-label="关闭"
                        title="关闭"
                        onClick={onClose}
                    >
                        <X className="h-6 w-6" aria-hidden="true" />
                    </Button>
                </div>

                <div className="grid min-h-0 flex-1 grid-cols-1 overflow-auto md:grid-cols-2">
                    <section className="space-y-3 border-b border-slate-200 p-4 dark:border-slate-800 md:border-b-0 md:border-r">
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">front</div>
                        {mediaLoading && <div className="text-xs text-slate-500 dark:text-slate-400">正在加载媒体…</div>}
                        {view.frontMediaNames.filter((name) => getMediaType(name)).length > 0 && (
                            <div className="flex flex-wrap gap-2">
                                {view.frontMediaNames.map((name) => (
                                    <MediaButton key={name} cardId={card.id} name={name} onOpen={setMediaModal} />
                                ))}
                            </div>
                        )}
                        <div className="whitespace-pre-line text-base leading-relaxed text-slate-900 dark:text-slate-100">
                            {view.frontSchema
                                ? renderPrompt(view.frontSchema, {
                                    userAnswer: [] as UserAnswer,
                                    setUserAnswer: undefined,
                                    disabled: true,
                                })
                                : view.frontClean}
                        </div>
                    </section>

                    <section className="space-y-3 p-4">
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">back</div>
                        {view.backMediaNames.filter((name) => getMediaType(name)).length > 0 && (
                            <div className="flex flex-wrap gap-2">
                                {view.backMediaNames.map((name) => (
                                    <MediaButton
                                        key={name}
                                        cardId={card.id}
                                        name={name}
                                        note={view.mediaNotes[name]}
                                        onOpen={setMediaModal}
                                    />
                                ))}
                            </div>
                        )}
                        <div className="whitespace-pre-line text-base leading-relaxed text-slate-900 dark:text-slate-100">
                            {view.frontSchema && view.backSchema
                                ? renderAnswer(view.frontSchema, view.backSchema)
                                : view.backClean}
                        </div>
                        {footerForRender && (
                            <div className="border-t border-slate-200 pt-3 text-sm text-slate-700 dark:border-slate-800 dark:text-slate-200">
                                <MarkdownText content={footerForRender} />
                            </div>
                        )}
                    </section>
                </div>
            </div>

            {mediaModal && (
                <div
                    className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
                    onClick={(event) => {
                        event.stopPropagation();
                        setMediaModal(null);
                    }}
                >
                    <div
                        className="max-h-[95vh] w-full max-w-5xl overflow-auto rounded-lg bg-white p-4 shadow-2xl dark:bg-slate-900"
                        onClick={(event) => event.stopPropagation()}
                    >
                        <div className="mb-3 flex items-center justify-between gap-3">
                            <div className="min-w-0 truncate text-sm text-slate-600 dark:text-slate-300">{mediaModal.name}</div>
                            <Button
                                type="button"
                                variant="link"
                                className="gap-1 px-2 py-1 text-sm"
                                onClick={() => setMediaModal(null)}
                            >
                                <X className="h-4 w-4" />
                                关闭
                            </Button>
                        </div>
                        {getMediaType(mediaModal.name) === "dot" ? (
                            <DotRender cardId={mediaModal.cardId} fileName={mediaModal.name} className="w-full" />
                        ) : getMediaType(mediaModal.name) === "map" ? (
                            <MapPdfViewer cardId={mediaModal.cardId} filename={mediaModal.name} className="w-full" />
                        ) : getMediaType(mediaModal.name) === "image" ? (
                            <ImageRender cardId={mediaModal.cardId} fileName={mediaModal.name} className="w-full" />
                        ) : (
                            <div className="text-sm text-rose-500">暂不支持的文件类型：{mediaModal.name}</div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
