import React, {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { Plus, Minus, RotateCcw, RotateCw, RefreshCw } from "lucide-react";
import { Button } from "./Button.tsx";
import { supabase } from "../../../lib/supabaseClient";
import type { PDFPageProxy } from "pdfjs-dist";

// 按容器尺寸的 3x 渲染
const RENDER_MULTIPLIER = 2;
//const SCALE_MULTIPLIER = 0.667;
const SIGNED_URL_TTL_SECONDS = 24 * 60 * 60; // 1 day
const SIGNED_URL_CACHE_TTL_MS = 12 * 60 * 60 * 1000; // cache for 12 hours
const signedUrlCache = new Map<string, { url: string; expiresAt: number }>();

// 让 pdf.js worker 在 Vite 下正确解析
import workerSrc from "pdfjs-dist/build/pdf.worker.min.mjs?url";
pdfjs.GlobalWorkerOptions.workerSrc = workerSrc;

interface MapPdfViewerProps {
    cardId: string;
    filename: string;
    pageNumber?: number;
    onClose?: () => void;
    className?: string;
}

type NineGridPos =
    | "left"
    | "right"
    | "up"
    | "down"
    | "center"
    | "middle"
    | "左"
    | "右"
    | "上"
    | "下"
    | "中";

const clamp = (value: number, min: number, max: number) =>
    Math.min(max, Math.max(min, value));

type MapFileConfig = {
    map_file: string;
    name: string;
    page: number;
    position?: NineGridPos;
};

const isRecord = (val: unknown): val is Record<string, unknown> =>
    typeof val === "object" && val !== null;

const getStringField = (obj: Record<string, unknown>, key: keyof MapFileConfig) => {
    const v = obj[key as string];
    return typeof v === "string" ? v : undefined;
};

const getNumberField = (obj: Record<string, unknown>, key: keyof MapFileConfig) => {
    const v = obj[key as string];
    if (typeof v === "number") return v;
    if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) {
        return Number(v);
    }
    return undefined;
};
/**
 * 单页 PDF 查看组件：固定 3x 高清渲染，支持缩放、拖动、旋转、重置。
 * 仅在首次加载/重置/切换文件时自适配窗口，不会覆盖用户缩放。
 */
export const MapPdfViewer: React.FC<MapPdfViewerProps> = ({
    cardId,
    filename,
    className = "",
}) => {
    const minScale = 0.2;
    const maxScale = 3;
    const containerRef = useRef<HTMLDivElement>(null);
    const dragStartRef = useRef<{ x: number; y: number } | null>(null);
    const storageKey = useMemo(
        () => (cardId && filename ? `${cardId}/${filename}` : ""),
        [cardId, filename]
    );

    const [containerSize, setContainerSize] = useState<{ width: number; height: number }>({
        width: 0,
        height: 0,
    });
    const [pageSize, setPageSize] = useState<{ width: number; height: number } | null>(null);
    const [scale, setScale] = useState(1);
    const [rotation, setRotation] = useState(0);
    const [offset, setOffset] = useState({ x: 0, y: 0 });
    const [dragging, setDragging] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [pageRenderSize, setPageRenderSize] = useState<{ width: number; height: number } | null>(null);
    const [mapLoading, setMapLoading] = useState(false);
    const [mapError, setMapError] = useState<string | null>(null);

    const [pdfFileTitle, setPdfFileTitle] = useState<string | null>("");
    const [pdfFileUrl, setPdfFileUrl] = useState<string | null>(null);
    const [posOfGrid, setPosOfGrid] = useState<NineGridPos | undefined>("center");
    //const effectivePos = mapRefProps?.posOf3x3 ?? "center";
    //const effectiveTitle = mapRefProps?.title ?? "地图 PDF 预览";
    const resolveGrid = useCallback((pos: NineGridPos | undefined): { row: number; col: number } => {
        const text = (pos ?? "").toLowerCase();
        let row: 0 | 1 | 2 = 1;
        let col: 0 | 1 | 2 = 1;
        const has = (key: string) => text.includes(key);

        if (has("中") || has("middle") || has("center")) {
            row = 1;
            col = 1;
        }
        if (has("上") || has("up")) row = 0;
        if (has("下") || has("down")) row = 2;
        if (has("左") || has("left")) col = 0;
        if (has("右") || has("right")) col = 2;

        return { row, col };
    }, []);

    const initialGrid = useMemo(() => resolveGrid(posOfGrid), [posOfGrid, resolveGrid]);

    const [activeGrid, setActiveGrid] = useState<{ row: number; col: number } | null>(initialGrid);
    const [hasFitted, setHasFitted] = useState(false);

    const clampOffsetXY = useCallback(
        (
            currentX: number,
            currentY: number,
            nextScale: number,
            grid: { row: number; col: number } | null | undefined
        ) => {
            if (!containerSize.width || !containerSize.height || !pageSize) {
                return { x: currentX, y: currentY };
            }

            const baseW =
                (containerSize.width || pageSize.width) * RENDER_MULTIPLIER;
            const baseH = baseW * (pageSize.height / pageSize.width);
            const displayedWidth = baseW * nextScale;
            const displayedHeight = baseH * nextScale;

            const halfW = displayedWidth / 2;
            const halfH = displayedHeight / 2;
            const cx = containerSize.width / 2;
            const cy = containerSize.height / 2;

            let nextX = currentX;
            let nextY = currentY;

            if (grid?.col === 0) {
                const leftEdge = cx + nextX - halfW;
                if (leftEdge > 0) nextX -= leftEdge;
            }
            if (grid?.col === 2) {
                const rightEdge = cx + nextX + halfW;
                if (rightEdge < containerSize.width) {
                    nextX += containerSize.width - rightEdge;
                }
            }

            if (grid?.row === 0) {
                const topEdge = cy + nextY - halfH;
                if (topEdge > 0) nextY -= topEdge;
            }
            if (grid?.row === 2) {
                const bottomEdge = cy + nextY + halfH;
                if (bottomEdge < containerSize.height) {
                    nextY += containerSize.height - bottomEdge;
                }
            }

            return { x: nextX, y: nextY };
        },
        [containerSize.width, containerSize.height, pageSize]
    );

    // 监听容器尺寸
    useEffect(() => {
        if (!containerRef.current) return;
        const observer = new ResizeObserver((entries) => {
            const entry = entries[0];
            if (entry?.contentRect) {
                setContainerSize({
                    width: entry.contentRect.width,
                    height: entry.contentRect.height,
                });
            }
        });
        observer.observe(containerRef.current);
        return () => observer.disconnect();
    }, []);

    const getSignedUrlWithCache = useCallback(async (bucket: string, path: string) => {
        const cacheKey = `${bucket}:${path}`;
        const now = Date.now();
        const cached = signedUrlCache.get(cacheKey);
        if (cached && cached.expiresAt > now) {
            return cached.url;
        }
        const { data, error } = await supabase.storage
            .from(bucket)
            .createSignedUrl(path, SIGNED_URL_TTL_SECONDS);
        if (error || !data?.signedUrl) {
            throw new Error(error?.message || "无法获取签名链接");
        }
        const ttl = Math.min(SIGNED_URL_CACHE_TTL_MS, SIGNED_URL_TTL_SECONDS * 1000);
        signedUrlCache.set(cacheKey, {
            url: data.signedUrl,
            expiresAt: now + ttl,
        });
        return data.signedUrl;
    }, []);

    // 加载 .map 文件，解析出 PDF 及视图配置
    useEffect(() => {
        let active = true;
            async function loadMap() {
            if (!storageKey) {
                setMapError("缺少 cardId 或 filename");
                setPdfFileUrl(null);
                return;
            }
            setMapLoading(true);
            setMapError(null);
            setError(null);
            try {
                const signedMapUrl = await getSignedUrlWithCache("quizit_card_medias", storageKey);
                const resp = await fetch(signedMapUrl);
                if (!resp.ok) {
                    throw new Error(`下载失败 (${resp.status})`);
                }
                const content = await resp.text();
                const parsedRaw = JSON.parse(content) as unknown;
                if (!isRecord(parsedRaw)) {
                    throw new Error("map 文件不是有效 JSON 对象");
                }
                const parsed = parsedRaw as MapFileConfig;
                if (!active) return;

                const mapFile = getStringField(parsed, "map_file");
                const pageFromMap = getNumberField(parsed, "page");
                const pagePosition = getStringField(parsed, "position");
                const mapName = getStringField(parsed, "name");

                if (!mapFile || pageFromMap === undefined) {
                    throw new Error("map 文件缺少 map_file 或 page");
                }
                const normalizedMapFile = mapFile.replace(/^\/+/, "");
                const mapFilePage = `maps/${normalizedMapFile}/page_${pageFromMap}.pdf`;
                const signedPdfUrl = await getSignedUrlWithCache("quizit_big_medias", mapFilePage);
                setPdfFileUrl(signedPdfUrl);
                setPdfFileTitle(mapName ?? "");
                setPosOfGrid(pagePosition as NineGridPos | undefined);
            } catch (err) {
                if (active) {
                    const message = err instanceof Error ? err.message : "加载 map 文件失败";
                    setMapError(message);
                }
            } finally {
                if (active) {
                    setMapLoading(false);
                }
            }
        }
        loadMap();
        return () => {
            active = false;
        };
    }, [storageKey, getSignedUrlWithCache]);

    const handleZoom = useCallback(
        (delta: number) => {
            setScale((prev) => {
                const next = clamp(prev + delta, minScale, maxScale);
                const grid = activeGrid ?? { row: 1, col: 1 };
                setOffset((prevOffset) => clampOffsetXY(prevOffset.x, prevOffset.y, next, grid));
                return next;
            });
        },
        [minScale, maxScale, clampOffsetXY, activeGrid]
    );

    const rotate = useCallback((deg: number) => {
        setRotation((prev) => {
            const next = prev + deg;
            return ((next % 360) + 360) % 360;
        });
    }, []);

    // 容器宽度驱动渲染宽度（按容器尺寸的 2x 渲染）
    const renderWidth = useMemo(() => {
        return containerSize.width ? containerSize.width * RENDER_MULTIPLIER : undefined;
    }, [containerSize.width]);

    const calcFitScale = useCallback(() => {
        if (!pageSize || !containerSize.width || !containerSize.height) return null;
        const baseW = renderWidth ?? containerSize.width * RENDER_MULTIPLIER;
        const baseH = baseW * (pageSize.height / pageSize.width);
        const widthScale = containerSize.width / baseW;
        const heightScale = containerSize.height / baseH;
        return clamp(Math.min(widthScale, heightScale), minScale, maxScale);
    }, [containerSize.height, containerSize.width, pageSize, minScale, maxScale, renderWidth]);

    const resetView = useCallback(() => {
        if (!pageSize || !containerSize.width || !containerSize.height) return;
        const fit = calcFitScale();
        const fitScale = fit ?? 1;
        setScale(fitScale);
        setRotation(0);
        setOffset(clampOffsetXY(0, 0, fitScale, { row: 1, col: 1 }));
        setActiveGrid({ row: 1, col: 1 });
        setHasFitted(true);
    }, [calcFitScale, clampOffsetXY, pageSize, containerSize.width, containerSize.height]);

    // PDF 资源配置
    const fileConfig = useMemo(() => {
        if (!pdfFileUrl) return null;
        return {
            url: pdfFileUrl,
            withCredentials: false,
        } as const;
    }, [pdfFileUrl]);

    const pageTransform = useMemo(
        () => `translate(${offset.x}px, ${offset.y}px)`,
        [offset.x, offset.y]
    );

    const centerToGridCell = useCallback(
        (row: number, col: number) => {
            if (!pageSize || !containerSize.width || !containerSize.height) return;

            // 中心格：先计算适配，再应用居中
            if (row === 1 && col === 1) {
                const fit = calcFitScale();
                const fitScale = fit ?? 1;
                setScale(fitScale);
                setOffset(clampOffsetXY(0, 0, fitScale, { row, col }));
                setRotation(0);
                setActiveGrid({ row, col });
                return;
            }

            // 非中心格：用实际渲染宽度近似页面尺寸，避免偏移误差
            const baseW =
                renderWidth ??
                ((containerSize.width || pageSize.width) * RENDER_MULTIPLIER);
            const baseH = baseW * (pageSize.height / pageSize.width);
            const displayedWidth = baseW;
            const displayedHeight = baseH;
            const cellX = (col - 1) * (displayedWidth / 3);
            const cellY = (row - 1) * (displayedHeight / 3);

            setScale(1);
            setOffset(clampOffsetXY(-cellX, -cellY, 1, { row, col }));
            setActiveGrid({ row, col });
        },
        [pageSize, calcFitScale, clampOffsetXY, containerSize.width, containerSize.height, renderWidth]
    );

    const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
        if (e.button !== 0) return;
        e.currentTarget.setPointerCapture(e.pointerId);
        dragStartRef.current = { x: e.clientX, y: e.clientY };
        setDragging(true);
    };

    const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
        if (!dragging || !dragStartRef.current) return;
        const dx = e.clientX - dragStartRef.current.x;
        const dy = e.clientY - dragStartRef.current.y;
        dragStartRef.current = { x: e.clientX, y: e.clientY };
        setOffset((prev) => ({ x: prev.x + dx, y: prev.y + dy }));
    };

    const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
        if (dragStartRef.current) {
            e.currentTarget.releasePointerCapture(e.pointerId);
        }
        dragStartRef.current = null;
        setDragging(false);
    };

    useEffect(() => {
        if (hasFitted) return;
        if (!pageSize || !containerSize.width || !containerSize.height) return;

        // 初次定位：根据传入的初始九宫格位置
        if (initialGrid.row === 1 && initialGrid.col === 1) {
            resetView();
        } else {
            centerToGridCell(initialGrid.row, initialGrid.col);
        }
        setHasFitted(true);
    }, [
        hasFitted,
        pageSize,
        containerSize.width,
        containerSize.height,
        resetView,
        centerToGridCell,
        initialGrid.row,
        initialGrid.col,
    ]);

    // 切换 PDF 时允许重新自适配
    useEffect(() => {
        setHasFitted(false);
        setActiveGrid(initialGrid);
    }, [pdfFileUrl, posOfGrid, initialGrid]);

    return (
        <div
            className={`relative max-w-5xl w-full rounded-2xl border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900 ${className}`}
        >
            <div
                ref={containerRef}
                className="relative h-[75vh] bg-slate-950/80 overflow-hidden rounded-b-2xl flex items-center justify-center"
            >
                <div className="absolute top-3 right-3 z-10 flex items-center gap-2 bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm px-3 py-2 rounded-full shadow-lg">
                    <div className="text-xs font-semibold text-slate-700 dark:text-slate-200 mr-1">
                        {pdfFileTitle}
                    </div>
                    <Button
                        type="button"
                        variant="ghost"
                        className="px-2 py-1 text-xs"
                        onClick={() => handleZoom(0.2)}
                        aria-label="放大"
                    >
                        <Plus className="w-4 h-4" />
                    </Button>
                    <Button
                        type="button"
                        variant="ghost"
                        className="px-2 py-1 text-xs"
                        onClick={() => handleZoom(-0.2)}
                        aria-label="缩小"
                    >
                        <Minus className="w-4 h-4" />
                    </Button>
                    <Button
                        type="button"
                        variant="ghost"
                        className="px-2 py-1 text-xs"
                        onClick={() => rotate(-90)}
                        aria-label="逆时针旋转 90 度"
                    >
                        <RotateCcw className="w-4 h-4" />
                    </Button>
                    <Button
                        type="button"
                        variant="ghost"
                        className="px-2 py-1 text-xs"
                        onClick={() => rotate(90)}
                        aria-label="顺时针旋转 90 度"
                    >
                        <RotateCw className="w-4 h-4" />
                    </Button>
                    <Button
                        type="button"
                        variant="ghostSecond"
                        className="px-2 py-1 text-xs"
                        onClick={resetView}
                        aria-label="重置视图"
                    >
                        <RefreshCw className="w-4 h-4" />
                    </Button>
                    <div
                        className="hidden sm:grid grid-cols-3 grid-rows-3 gap-[1px] border border-emerald-200 bg-emerald-50 overflow-hidden dark:border-slate-600 dark:bg-slate-800/80"
                        style={{ width: "44px", height: "32px" }}
                    >
                        {[0, 1, 2].map((r) =>
                            [0, 1, 2].map((c) => {
                                const active = activeGrid?.row === r && activeGrid.col === c;
                                return (
                                    <button
                                        key={`${r}-${c}`}
                                        type="button"
                                        className={[
                                            "w-full h-full p-0 m-0 leading-none text-transparent transition-colors flex items-center justify-center",
                                            active
                                                ? "bg-emerald-500/80 dark:bg-sky-500/70"
                                                : "bg-slate-100 dark:bg-slate-700",
                                            "hover:bg-emerald-100 dark:hover:bg-sky-600/60",
                                            "active:bg-emerald-200 dark:active:bg-sky-700/80",
                                        ].join(" ")}
                                        onClick={() => centerToGridCell(r, c)}
                                        disabled={!pageRenderSize}
                                        title={`定位到第 ${r + 1} 行第 ${c + 1} 列`}
                                    >
                                        {r === 1 && c === 1 ? (
                                            <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 dark:bg-sky-400" />
                                        ) : (
                                            "·"
                                        )}
                                    </button>
                                );
                            })
                        )}
                    </div>
                </div>
                {mapLoading && (
                    <div className="text-sm text-slate-200 text-center py-6">
                        正在加载地图配置…
                    </div>
                )}
                {mapError && !mapLoading && (
                    <div className="text-sm text-rose-200 text-center py-6">
                        {mapError}
                    </div>
                )}
                {!mapLoading && !mapError && fileConfig && (
                    <Document
                        file={fileConfig}
                        onLoadSuccess={() => {
                            setError(null);
                        }}
                        onLoadError={(err) => {
                            console.error("pdf load error", err);
                            setError("PDF 加载失败，请检查链接或鉴权。");
                        }}
                        loading={
                            <div className="text-sm text-slate-200 text-center py-6">
                                正在加载 PDF…
                            </div>
                        }
                        error={
                            <div className="text-sm text-rose-300 text-center py-6">
                                PDF 加载失败。
                            </div>
                        }
                    >
                        <div
                            className="relative"
                            style={{
                                cursor: dragging ? "grabbing" : "grab",
                            }}
                            onPointerDown={handlePointerDown}
                            onPointerMove={handlePointerMove}
                            onPointerUp={endDrag}
                            onPointerCancel={endDrag}
                        >
                            <div
                                className="transform-gpu"
                                style={{
                                    transform: pageTransform,
                                    transformOrigin: "center center",
                                }}
                            >
                                <Page
                                    pageNumber={1}
                                    width={renderWidth}
                                    scale={scale}
                                    rotate={rotation}
                                    renderAnnotationLayer={false}
                                    renderTextLayer={false}
                                    className="shadow-lg"
                                    onLoadSuccess={(page: PDFPageProxy) => {
                                        const viewport = page.getViewport({ scale: 1 });
                                        const w = viewport?.width;
                                        const h = viewport?.height;
                                        if (!w || !h) return;
                                        setPageRenderSize({
                                            width: w ?? 0,
                                            height: h ?? 0,
                                        });
                                        setPageSize((prev) => {
                                            if (prev && prev.width === w && prev.height === h) {
                                                return prev;
                                            }
                                            return { width: w, height: h };
                                        });
                                    }}
                                />
                            </div>
                        </div>
                </Document>
                )}
                {error && (
                    <div className="absolute bottom-2 left-1/2 -translate-x-1/2 text-xs text-rose-300 text-center px-3 py-1 bg-rose-900/70 rounded-lg">
                        {error}
                    </div>
                )}
            </div>
        </div>
    );
};
