import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { supabase } from "../../lib/supabaseClient";
import { Button } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { Image as ImageIcon, Upload, Download, Trash2, CornerUpLeft } from "lucide-react";

interface DeckRow {
    id: string;
    title: string;
    description: string | null;
    items: { items: { card_id: string; position: number }[] } | null;
}

interface DeckItem {
    card_id: string;
    position: number;
}

interface CardRow {
    id: string;
    front: string;
    back: string;
}

type ResourceFile = {
    name: string;
    id?: string;
    updated_at?: string;
    created_at?: string;
    metadata?: {
        size?: number;
        mimetype?: string;
    };
};

const BUCKET_NAME = "quizit_card_medias";
const SIGNED_URL_TTL = 600;
const ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png", "dot", "map"];
const MAX_MEDIA_BYTES = 50 * 1024;

function formatBytes(bytes?: number) {
    if (!bytes && bytes !== 0) return "-";
    if (bytes < 1024) return `${bytes} B`;
    const kb = bytes / 1024;
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    return `${(kb / 1024).toFixed(1)} MB`;
}

function isImageFile(name: string) {
    const ext = name.split(".").pop()?.toLowerCase();
    return Boolean(ext && ["png", "jpg", "jpeg", "gif", "webp"].includes(ext));
}

function isAllowedFile(name: string) {
    const ext = name.split(".").pop()?.toLowerCase();
    return Boolean(ext && ALLOWED_EXTENSIONS.includes(ext));
}

function getFileExtension(name: string) {
    return name.split(".").pop()?.toLowerCase() ?? "";
}

function getNextIndex(files: ResourceFile[], side: "front" | "back") {
    const pattern = new RegExp(`^${side}(\\d+)\\.`, "i");
    let maxIndex = 0;
    files.forEach((file) => {
        const match = file.name.match(pattern);
        if (match) {
            const idx = Number(match[1]);
            if (!Number.isNaN(idx)) {
                maxIndex = Math.max(maxIndex, idx);
            }
        }
    });
    return maxIndex + 1;
}

function buildSideFilename(
    usedNames: Set<string>,
    startIndex: number,
    side: "front" | "back",
    ext: string
) {
    const safeExt = ext ? ext.toLowerCase() : "jpg";
    let index = startIndex;
    let candidate = `${side}${index}.${safeExt}`;
    while (usedNames.has(candidate.toLowerCase())) {
        index += 1;
        candidate = `${side}${index}.${safeExt}`;
    }
    return { name: candidate, nextIndex: index + 1 };
}

function replaceWithJpg(name: string) {
    if (name.toLowerCase().endsWith(".jpg") || name.toLowerCase().endsWith(".jpeg")) {
        return name.replace(/\.jpeg$/i, ".jpg");
    }
    if (name.includes(".")) {
        return name.replace(/\.[^.]+$/, ".jpg");
    }
    return `${name}.jpg`;
}

async function compressImageToSize(file: File, maxBytes: number): Promise<File | null> {
    const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as string);
        reader.onerror = () => reject(new Error("read image failed"));
        reader.readAsDataURL(file);
    });

    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
        const image = new window.Image();
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error("load image failed"));
        image.src = dataUrl;
    });

    const baseWidth = img.width;
    const baseHeight = img.height;

    for (let attempt = 0; attempt < 12; attempt += 1) {
        const scale = Math.max(0.2, 1 - attempt * 0.08);
        const quality = Math.max(0.35, 0.9 - attempt * 0.05);
        const reduceColors = attempt >= 4;
        const width = Math.max(1, Math.round(baseWidth * scale));
        const height = Math.max(1, Math.round(baseHeight * scale));

        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        if (!ctx) return null;
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

        if (reduceColors) {
            const imageData = ctx.getImageData(0, 0, width, height);
            const data = imageData.data;
            const levels = 32;
            const step = 256 / levels;
            for (let i = 0; i < data.length; i += 4) {
                data[i] = Math.round(data[i] / step) * step;
                data[i + 1] = Math.round(data[i + 1] / step) * step;
                data[i + 2] = Math.round(data[i + 2] / step) * step;
            }
            ctx.putImageData(imageData, 0, 0);
        }

        const blob = await new Promise<Blob | null>((resolve) =>
            canvas.toBlob((b) => resolve(b), "image/jpeg", quality)
        );

        console.debug(
            "compressImageToSize",
            file.name,
            { attempt, width, height, quality, reduceColors, size: blob?.size ?? 0 }
        );

        if (blob && blob.size <= maxBytes) {
            const nextName = replaceWithJpg(file.name);
            return new File([blob], nextName, { type: "image/jpeg" });
        }
    }

    return null;
}

function startsWithSide(name: string, side: "front" | "back") {
    return name.toLowerCase().startsWith(side);
}

function hasImageCaption(text: string) {
    return /!\[[^\]]+\]/.test(text);
}

export default function DeckResourcesPage() {
    const { deckId } = useParams<{ deckId: string }>();
    const navigate = useNavigate();

    const [loading, setLoading] = useState(true);
    const [loadingResources, setLoadingResources] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [deck, setDeck] = useState<DeckRow | null>(null);
    const [cards, setCards] = useState<CardRow[]>([]);
    const [resourceMap, setResourceMap] = useState<Record<string, ResourceFile[]>>({});
    const [previewMap, setPreviewMap] = useState<Record<string, string>>({});
    const [uploadCardId, setUploadCardId] = useState("");
    const [uploadSide, setUploadSide] = useState<"front" | "back">("front");
    const [uploading, setUploading] = useState(false);
    const [uploadError, setUploadError] = useState<string | null>(null);
    const [deletingPath, setDeletingPath] = useState<string | null>(null);
    const [previewImage, setPreviewImage] = useState<{ url: string; name: string } | null>(null);
    const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
    const [deleteTarget, setDeleteTarget] = useState<{ cardId: string; fileName: string } | null>(null);
    const fileInputRef = useRef<HTMLInputElement | null>(null);

    useEffect(() => {
        if (!deckId) return;

        async function loadDeck() {
            setLoading(true);
            setError(null);

            const { data: deckData, error: deckError } = await supabase
                .from("decks")
                .select("id, title, description, items")
                .eq("id", deckId)
                .single();

            if (deckError || !deckData) {
                console.error("load deck error", deckError);
                setError("加载 deck 失败");
                setLoading(false);
                return;
            }

            const typedDeck = deckData as DeckRow;
            setDeck(typedDeck);

            const rawItems = (typedDeck.items?.items ?? []) as DeckItem[];
            const cardIds = rawItems.map((it) => it.card_id).filter(Boolean);

            if (cardIds.length === 0) {
                setCards([]);
                setLoading(false);
                return;
            }

            const { data: cardsData, error: cardsError } = await supabase
                .from("cards")
                .select("id, front, back")
                .in("id", cardIds);

            if (cardsError || !cardsData) {
                console.error("load cards error", cardsError);
                setError("加载卡片失败");
                setLoading(false);
                return;
            }

            const cardsById = new Map(cardsData.map((c) => [c.id, c]));
            const orderedCards: CardRow[] = rawItems
                .map((it) => cardsById.get(it.card_id))
                .filter((c): c is CardRow => !!c);

            setCards(orderedCards);
            setLoading(false);
        }

        void loadDeck();
    }, [deckId]);

    useEffect(() => {
        if (cards.length > 0 && !uploadCardId) {
            setUploadCardId(cards[0].id);
        }
    }, [cards, uploadCardId]);

    async function fetchCardResources(cardId: string) {
        const { data: list, error: listError } = await supabase
            .storage
            .from(BUCKET_NAME)
            .list(`${cardId}`);

        if (listError || !list) {
            console.error("list resources error", listError);
            return { files: [] as ResourceFile[], previews: {} as Record<string, string> };
        }

        const files = list as ResourceFile[];
        const imagePaths = files
            .filter((file) => isImageFile(file.name))
            .map((file) => `${cardId}/${file.name}`);

        if (imagePaths.length === 0) {
            return { files, previews: {} as Record<string, string> };
        }

        const { data: signedData, error: signedError } = await supabase
            .storage
            .from(BUCKET_NAME)
            .createSignedUrls(imagePaths, SIGNED_URL_TTL);

        if (signedError || !signedData) {
            console.error("sign urls error", signedError);
            return { files, previews: {} as Record<string, string> };
        }

        const previews: Record<string, string> = {};
        signedData.forEach((item) => {
            if (item?.path && item?.signedUrl) {
                previews[item.path] = item.signedUrl;
            }
        });

        return { files, previews };
    }

    async function loadAllResources() {
        if (cards.length === 0) return;
        setLoadingResources(true);
        setError(null);

        try {
            const results = await Promise.all(
                cards.map(async (card) => {
                    const payload = await fetchCardResources(card.id);
                    return { cardId: card.id, ...payload };
                })
            );

            const nextResources: Record<string, ResourceFile[]> = {};
            const nextPreviews: Record<string, string> = {};

            results.forEach(({ cardId, files, previews }) => {
                nextResources[cardId] = files;
                Object.assign(nextPreviews, previews);
            });

            setResourceMap(nextResources);
            setPreviewMap(nextPreviews);
        } catch (e) {
            console.error("load resources error", e);
            setError("加载资源失败");
        } finally {
            setLoadingResources(false);
        }
    }

    useEffect(() => {
        void loadAllResources();
    }, [cards]);

    function updateCardResources(cardId: string, files: ResourceFile[], previews: Record<string, string>) {
        setResourceMap((prev) => ({ ...prev, [cardId]: files }));
        setPreviewMap((prev) => {
            const next = { ...prev };
            Object.keys(next).forEach((key) => {
                if (key.startsWith(`${cardId}/`)) {
                    delete next[key];
                }
            });
            return { ...next, ...previews };
        });
    }

    async function refreshCardResources(cardId: string) {
        const { files, previews } = await fetchCardResources(cardId);
        updateCardResources(cardId, files, previews);
    }

    function handleUploadClick(side: "front" | "back") {
        setUploadSide(side);
        fileInputRef.current?.click();
    }

    async function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
        const fileList = e.target.files;
        if (!fileList || fileList.length === 0) return;
        if (!uploadCardId) {
            setUploadError("请先选择要上传的卡片。");
            return;
        }

        setUploading(true);
        setUploadError(null);

        const files = Array.from(fileList);
        const uploadFiles: File[] = [];
        const errors: string[] = [];

        for (const file of files) {
            if (!isAllowedFile(file.name)) {
                errors.push(`${file.name} 格式不支持`);
                continue;
            }

            const ext = getFileExtension(file.name);
            if ((ext === "dot" || ext === "map") && file.size > MAX_MEDIA_BYTES) {
                errors.push(`${file.name} 文件过大（超过 50KB）`);
                continue;
            }

            if ((ext === "jpg" || ext === "jpeg" || ext === "png") && file.size > MAX_MEDIA_BYTES) {
                const compressed = await compressImageToSize(file, MAX_MEDIA_BYTES);
                if (!compressed) {
                    errors.push(`${file.name} 压缩失败`);
                    continue;
                }
                uploadFiles.push(compressed);
                continue;
            }

            uploadFiles.push(file);
        }

        if (uploadFiles.length === 0) {
            setUploadError(errors.length ? errors.join("；") : "仅支持 jpg/png/dot/map 文件。");
            setUploading(false);
            e.target.value = "";
            return;
        }

        if (errors.length > 0) {
            setUploadError(errors.join("；"));
        }
        const existingFiles = resourceMap[uploadCardId] ?? [];
        const usedNames = new Set(existingFiles.map((file) => file.name.toLowerCase()));
        let nextIndex = getNextIndex(existingFiles, uploadSide);
        const preparedUploads = uploadFiles.map((file) => {
            const ext = getFileExtension(file.name);
            const built = buildSideFilename(usedNames, nextIndex, uploadSide, ext);
            usedNames.add(built.name.toLowerCase());
            nextIndex = built.nextIndex;
            return { file, name: built.name };
        });

        const results = await Promise.all(
            preparedUploads.map(async ({ file, name }) => {
                const path = `${uploadCardId}/${name}`;
                const { error: uploadError } = await supabase
                    .storage
                    .from(BUCKET_NAME)
                    .upload(path, file, { upsert: true });
                return { path, error: uploadError };
            })
        );

        const failed = results.filter((r) => r.error);
        if (failed.length > 0) {
            console.error("upload files error", failed);
            setUploadError("部分文件上传失败，请重试。");
        }

        await refreshCardResources(uploadCardId);
        setUploading(false);
        e.target.value = "";
    }

    function handleDelete(cardId: string, fileName: string) {
        setDeleteTarget({ cardId, fileName });
        setShowDeleteConfirm(true);
    }

    async function handleDeleteConfirmed() {
        if (!deleteTarget) return;
        const { cardId, fileName } = deleteTarget;
        const path = `${cardId}/${fileName}`;
        setDeletingPath(path);
        const { error: removeError } = await supabase
            .storage
            .from(BUCKET_NAME)
            .remove([path]);

        if (removeError) {
            console.error("delete file error", removeError);
            setError("删除资源失败");
            setDeletingPath(null);
            return;
        }

        await refreshCardResources(cardId);
        setDeletingPath(null);
        setShowDeleteConfirm(false);
        setDeleteTarget(null);
    }

    async function handleDownload(cardId: string, fileName: string) {
        const path = `${cardId}/${fileName}`;
        const { data, error: signedError } = await supabase
            .storage
            .from(BUCKET_NAME)
            .createSignedUrl(path, SIGNED_URL_TTL);
        if (signedError || !data?.signedUrl) {
            console.error("download sign error", signedError);
            setError("下载失败");
            return;
        }
        window.open(data.signedUrl, "_blank", "noopener,noreferrer");
    }

    const cardEntries = useMemo(() => {
        return cards.map((card, idx) => {
            const files = resourceMap[card.id] ?? [];
            const frontFiles = files.filter((file) => startsWithSide(file.name, "front"));
            const backFiles = files.filter((file) => startsWithSide(file.name, "back"));
            const otherFiles = files.filter(
                (file) => !startsWithSide(file.name, "front") && !startsWithSide(file.name, "back")
            );
            return { card, index: idx, frontFiles, backFiles, otherFiles, total: files.length };
        });
    }, [cards, resourceMap]);

    const selectedEntry = useMemo(() => {
        if (!uploadCardId) return null;
        return cardEntries.find((entry) => entry.card.id === uploadCardId) ?? null;
    }, [cardEntries, uploadCardId]);

    const frontCaptions = useMemo(() => {
        const frontText = selectedEntry?.card.front ?? "";
        const matches = Array.from(frontText.matchAll(/!\[([^\]]+)\]/g));
        return matches.map((m) => m[1].trim()).filter(Boolean);
    }, [selectedEntry]);

    const backCaptions = useMemo(() => {
        const backText = selectedEntry?.card.back ?? "";
        const matches = Array.from(backText.matchAll(/!\[([^\]]+)\]/g));
        return matches.map((m) => m[1].trim()).filter(Boolean);
    }, [selectedEntry]);

    const frontImageCount = useMemo(() => {
        return selectedEntry?.frontFiles.filter((file) => isImageFile(file.name)).length ?? 0;
    }, [selectedEntry]);

    const backImageCount = useMemo(() => {
        return selectedEntry?.backFiles.filter((file) => isImageFile(file.name)).length ?? 0;
    }, [selectedEntry]);

    const extraFrontCaptions = useMemo(() => {
        return frontCaptions.slice(frontImageCount);
    }, [frontCaptions, frontImageCount]);

    const extraBackCaptions = useMemo(() => {
        return backCaptions.slice(backImageCount);
    }, [backCaptions, backImageCount]);

    const resourceListEntries = useMemo(() => {
        return cardEntries.filter((entry) => {
            if (entry.total > 0) return true;
            return hasImageCaption(entry.card.front) || hasImageCaption(entry.card.back);
        });
    }, [cardEntries]);

    if (!deckId) {
        return <div className="text-slate-700 dark:text-slate-200 px-4 py-6">缺少 deckId 参数。</div>;
    }

    if (loading) {
        return <div className="text-slate-700 dark:text-slate-200 px-4 py-6">正在加载 deck…</div>;
    }

    if (error && !deck) {
        return (
            <div className="px-4 py-6 space-y-4">
                <div className="text-base text-rose-600 border border-rose-200 bg-rose-50 rounded-xl px-3 py-2 dark:text-rose-400 dark:border-rose-500/50 dark:bg-rose-950/40">
                    {error}
                </div>
                <Button
                    type="button"
                    variant="link"
                    className="text-base px-0 text-emerald-700 hover:text-emerald-800 underline underline-offset-4 dark:text-sky-300 dark:hover:text-sky-200"
                    onClick={() => navigate(-1)}
                >
                    返回
                </Button>
            </div>
        );
    }

    if (!deck) {
        return (
            <div className="px-4 py-6 text-slate-700 dark:text-slate-200">
                未找到对应的 deck。
                <div className="mt-3">
                    <Button
                        type="button"
                        variant="link"
                        className="text-base px-0 text-emerald-700 hover:text-emerald-800 underline underline-offset-4 dark:text-sky-300 dark:hover:text-sky-200"
                        onClick={() => navigate(-1)}
                    >
                        返回
                    </Button>
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-6 text-slate-900 dark:text-slate-100 px-4 py-6 w-fit mx-auto">
            <div className="flex items-center justify-between gap-4">
                <div className="flex items-start gap-3 flex-1 min-w-0">
                    <ImageIcon className="w-10 h-10 text-emerald-600 dark:text-emerald-400" />
                    <div className="flex-1 min-w-0 space-y-1">
                        <div className="text-2xl font-semibold truncate">资源管理</div>
                        <div className="text-base text-slate-600 dark:text-slate-300 truncate">
                            {deck.title || "[未命名]"} · {cards.length} 张卡片
                        </div>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <Button
                        type="button"
                        variant="iconRound"
                        className="text-sky-500 hover:text-white hover:bg-sky-500 dark:text-sky-300 dark:hover:text-sky-100 dark:hover:bg-sky-700"
                        onClick={() => navigate(`/decks/${deckId}/edit`)}
                        title="返回编辑页"
                    >
                        <CornerUpLeft className="w-6 h-6" />
                    </Button>
                </div>
            </div>

            {error && (
                <div className="text-base text-rose-600 border border-rose-200 bg-rose-50 rounded-xl px-3 py-2 dark:text-rose-400 dark:border-rose-500/50 dark:bg-rose-950/40">
                    {error}
                </div>
            )}

            <div className="rounded-2xl border border-slate-200 bg-white/90 p-4 space-y-3 shadow-sm dark:border-slate-700 dark:bg-slate-900/70">
                <div className="flex flex-wrap items-center gap-3">
                    <div className="text-base font-semibold">选择卡片</div>
                    <div className="flex items-center gap-2">
                        <select
                            className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800 dark:bg-slate-950/70 dark:border-slate-700 dark:text-slate-100"
                            value={uploadCardId}
                            onChange={(e) => setUploadCardId(e.target.value)}
                        >
                            <option value="" disabled>
                                选择卡片
                            </option>
                            {cards.map((card, idx) => (
                                <option key={card.id} value={card.id}>
                                    {hasImageCaption(card.front) || hasImageCaption(card.back) ? "*" : ""}
                                    #{idx + 1} {card.front.slice(0, 20)} · {card.id.slice(0, 8)}
                                </option>
                            ))}
                        </select>
                        <Button
                            type="button"
                            variant="ghost"
                            className="text-sm"
                            onClick={loadAllResources}
                            disabled={loadingResources}
                        >
                            {loadingResources ? "刷新中…" : "刷新列表"}
                        </Button>
                        <input
                            ref={fileInputRef}
                            type="file"
                            multiple
                            accept=".jpg,.jpeg,.png,.dot,.map"
                            className="hidden"
                            onChange={handleFileSelected}
                        />
                    </div>
                </div>
            </div>

            <div className="space-y-4">
                {cards.length === 0 ? (
                    <div className="text-sm text-slate-500">当前 deck 还没有卡片。</div>
                ) : !selectedEntry ? (
                    <div className="text-sm text-slate-500">请选择一张卡片以管理资源。</div>
                ) : (
                    <div className="space-y-3">
                        <div className="rounded-xl border-2 border-dashed border-emerald-400/80 dark:border-emerald-300/70 p-3">
                            <div className="flex items-start justify-between gap-3 mb-3">
                                <div className="text-base font-semibold text-slate-800 dark:text-slate-100">
                                    #{selectedEntry.index + 1} {selectedEntry.card.front || "[无题]"}
                                </div>
                                <div className="text-xs text-slate-400 break-all">{selectedEntry.card.id}</div>
                            </div>
                            <div className="flex flex-wrap items-center gap-2 mb-3">
                                <div className="text-sm text-slate-500 dark:text-slate-400">
                                    上传规则：文件将保存为 {`{cardId}/front* 或 {cardId}/back*`}。
                                </div>
                            </div>
                            {uploadError && (
                                <div className="text-sm text-rose-600 dark:text-rose-400 mb-2">
                                    {uploadError}
                                </div>
                            )}
                            <div className="space-y-3">
                                <ResourceSection
                                    title="front"
                                    files={selectedEntry.frontFiles}
                                    cardId={selectedEntry.card.id}
                                    previewMap={previewMap}
                                    deletingPath={deletingPath}
                                    onDelete={handleDelete}
                                    onPreview={(url, name) => setPreviewImage({ url, name })}
                                    showDelete
                                    imageCaptions={frontCaptions}
                                    extraContent={
                                        extraFrontCaptions.length > 0 ? (
                                            <ul className="list-disc pl-5 text-sm text-slate-600 dark:text-slate-300">
                                                {extraFrontCaptions.map((caption, idx) => (
                                                    <li key={`${caption}-${idx}`}>{caption}</li>
                                                ))}
                                            </ul>
                                        ) : null
                                    }
                                    headerAction={
                                        <Button
                                            type="button"
                                            variant="outline"
                                            className="text-sm"
                                            onClick={() => handleUploadClick("front")}
                                            disabled={!uploadCardId || uploading}
                                        >
                                            <Upload className="w-4 h-4 mr-1" />
                                            {uploading && uploadSide === "front" ? "上传中…" : "上传文件"}
                                        </Button>
                                    }
                                />
                                <div className="border-t border-slate-200 dark:border-slate-700" />
                                <ResourceSection
                                    title="back"
                                    files={selectedEntry.backFiles}
                                    cardId={selectedEntry.card.id}
                                    previewMap={previewMap}
                                    deletingPath={deletingPath}
                                    onDelete={handleDelete}
                                    onPreview={(url, name) => setPreviewImage({ url, name })}
                                    showDelete
                                    imageCaptions={backCaptions}
                                    extraContent={
                                        extraBackCaptions.length > 0 ? (
                                            <ul className="list-disc pl-5 text-sm text-slate-600 dark:text-slate-300">
                                                {extraBackCaptions.map((caption, idx) => (
                                                    <li key={`${caption}-${idx}`}>{caption}</li>
                                                ))}
                                            </ul>
                                        ) : null
                                    }
                                    headerAction={
                                        <Button
                                            type="button"
                                            variant="outline"
                                            className="text-sm"
                                            onClick={() => handleUploadClick("back")}
                                            disabled={!uploadCardId || uploading}
                                        >
                                            <Upload className="w-4 h-4 mr-1" />
                                            {uploading && uploadSide === "back" ? "上传中…" : "上传文件"}
                                        </Button>
                                    }
                                />
                                {selectedEntry.otherFiles.length > 0 && (
                                    <ResourceSection
                                        title="其他"
                                        files={selectedEntry.otherFiles}
                                        cardId={selectedEntry.card.id}
                                        previewMap={previewMap}
                                        deletingPath={deletingPath}
                                        onDelete={handleDelete}
                                        onPreview={(url, name) => setPreviewImage({ url, name })}
                                        showDelete
                                    />
                                )}
                            </div>
                        </div>
                    </div>
                )}
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-sm dark:border-slate-700 dark:bg-slate-900/70 space-y-4">
                <div className="text-base font-semibold">资源列表</div>
                {resourceListEntries.length === 0 ? (
                    <div className="text-sm text-slate-500">暂无资源。</div>
                ) : (
                    <div className="space-y-3">
                        {resourceListEntries.map(({ card, index, frontFiles, backFiles, otherFiles, total }) => (
                            <div key={card.id} className="rounded-xl border border-slate-200 dark:border-slate-700 p-3">
                                <div className="flex items-start justify-between gap-3 mb-3">
                                    <div className="text-base font-semibold text-slate-800 dark:text-slate-100">
                                        #{index + 1} {card.front || "[无题]"}
                                    </div>
                                    <div className="text-xs text-slate-400 break-all">{card.id}</div>
                                </div>
                                {total === 0 ? (
                                    <div className="text-sm text-slate-500 dark:text-slate-400">暂无资源</div>
                                ) : (
                                    <div className="space-y-3">
                                        <ResourceSection
                                            title="front"
                                            files={frontFiles}
                                            cardId={card.id}
                                            previewMap={previewMap}
                                            deletingPath={deletingPath}
                                            onDownload={handleDownload}
                                            onPreview={(url, name) => setPreviewImage({ url, name })}
                                            showDownload
                                        />
                                        <ResourceSection
                                            title="back"
                                            files={backFiles}
                                            cardId={card.id}
                                            previewMap={previewMap}
                                            deletingPath={deletingPath}
                                            onDownload={handleDownload}
                                            onPreview={(url, name) => setPreviewImage({ url, name })}
                                            showDownload
                                        />
                                        {otherFiles.length > 0 && (
                                            <ResourceSection
                                                title="其他"
                                                files={otherFiles}
                                                cardId={card.id}
                                                previewMap={previewMap}
                                                deletingPath={deletingPath}
                                                onDownload={handleDownload}
                                                onPreview={(url, name) => setPreviewImage({ url, name })}
                                                showDownload
                                            />
                                        )}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {previewImage && (
                <div
                    className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 py-6"
                    onClick={() => setPreviewImage(null)}
                >
                    <div
                        className="relative max-h-full max-w-5xl w-full flex items-center justify-center"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <button
                            type="button"
                            className="absolute -top-3 -right-3 h-9 w-9 rounded-full bg-slate-900 text-slate-100 border border-slate-700"
                            onClick={() => setPreviewImage(null)}
                            aria-label="关闭预览"
                        >
                            ×
                        </button>
                        <img
                            src={previewImage.url}
                            alt={previewImage.name}
                            className="max-h-[85vh] max-w-full rounded-lg shadow-2xl"
                        />
                    </div>
                </div>
            )}
            <ConfirmDialog
                open={showDeleteConfirm}
                title="确认删除资源？"
                description={deleteTarget ? `将删除 ${deleteTarget.fileName}` : undefined}
                confirmLabel={deletingPath ? "删除中…" : "确认删除"}
                cancelLabel="取消"
                loading={Boolean(deletingPath)}
                onCancel={() => {
                    if (!deletingPath) {
                        setShowDeleteConfirm(false);
                        setDeleteTarget(null);
                    }
                }}
                onConfirm={() => {
                    void handleDeleteConfirmed();
                }}
            />
        </div>
    );
}

type ResourceSectionProps = {
    title: string;
    files: ResourceFile[];
    cardId: string;
    previewMap: Record<string, string>;
    deletingPath: string | null;
    onDelete?: (cardId: string, fileName: string) => void;
    onDownload?: (cardId: string, fileName: string) => void;
    onPreview: (url: string, name: string) => void;
    showDelete?: boolean;
    showDownload?: boolean;
    headerAction?: React.ReactNode;
    extraContent?: React.ReactNode;
    imageCaptions?: string[];
};

function ResourceSection({
    title,
    files,
    cardId,
    previewMap,
    deletingPath,
    onDelete,
    onDownload,
    onPreview,
    showDelete = false,
    showDownload = false,
    headerAction,
    extraContent,
    imageCaptions = [],
}: ResourceSectionProps) {
    let imageIndex = 0;
    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-semibold text-slate-500 dark:text-slate-400">{title}</div>
                {headerAction ? <div className="shrink-0">{headerAction}</div> : null}
            </div>
            {extraContent ? <div className="text-sm">{extraContent}</div> : null}
            {files.length === 0 ? (
                <div className="text-sm text-slate-500 dark:text-slate-400">暂无资源</div>
            ) : (
                <div className="space-y-2">
                    {files.map((file) => {
                        const path = `${cardId}/${file.name}`;
                        const previewUrl = previewMap[path];
                        const isImage = isImageFile(file.name);
                        const caption = isImage ? imageCaptions[imageIndex] : undefined;
                        if (isImage) {
                            imageIndex += 1;
                        }
                        return (
                            <div
                                key={file.name}
                                className="flex items-start gap-3 rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-2 text-sm"
                            >
                                {isImage ? (
                                    <button
                                        type="button"
                                        className="h-28 w-28 rounded-md border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 overflow-hidden"
                                        onClick={() => previewUrl && onPreview(previewUrl, file.name)}
                                        aria-label={`预览 ${file.name}`}
                                    >
                                        <img
                                            src={previewUrl}
                                            alt={file.name}
                                            className="h-full w-full object-cover"
                                        />
                                    </button>
                                ) : (
                                    <div className="h-14 w-14 rounded-md border border-dashed border-slate-300 dark:border-slate-600 flex items-center justify-center text-slate-400">
                                        文件
                                    </div>
                                )}
                                <div className="flex-1 min-w-0">
                                    <div className="font-mono text-slate-700 dark:text-slate-200 break-all">
                                        {file.name}
                                    </div>
                                    <div className="text-xs text-slate-500 dark:text-slate-400">
                                        {formatBytes(file.metadata?.size)}
                                        {file.updated_at ? ` · ${file.updated_at}` : ""}
                                        {caption ? (
                                            <>
                                                <br />
                                                {caption}
                                            </>
                                        ) : null}
                                    </div>
                                </div>
                                <div className="flex items-center gap-1">
                                    {showDownload && (
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            className="px-2 py-1 text-sm"
                                            onClick={() => onDownload?.(cardId, file.name)}
                                        >
                                            <Download className="w-4 h-4" />
                                        </Button>
                                    )}
                                    {showDelete && (
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            className="px-2 py-1 text-sm text-rose-500"
                                            onClick={() => onDelete?.(cardId, file.name)}
                                            disabled={deletingPath === path}
                                        >
                                            <Trash2 className="w-4 h-4" />
                                        </Button>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
