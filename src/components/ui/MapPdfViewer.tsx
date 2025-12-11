import React, {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { Plus, Minus, RotateCcw, RotateCw, RefreshCw, X } from "lucide-react";
import { Button } from "./Button.tsx";

// 按容器尺寸的 3x 渲染
const RENDER_MULTIPLIER = 2;
//const SCALE_MULTIPLIER = 0.667;

// 让 pdf.js worker 在 Vite 下正确解析
import workerSrc from "pdfjs-dist/build/pdf.worker.min.mjs?url";
pdfjs.GlobalWorkerOptions.workerSrc = workerSrc;

interface MapPdfViewerProps {
    pdfUrl: string;
    title?: string;
    pageNumber?: number;
    onClose?: () => void;
    className?: string;
    initialScale?: number;
    minScale?: number;
    maxScale?: number;
}

const clamp = (value: number, min: number, max: number) =>
    Math.min(max, Math.max(min, value));

/**
 * 单页 PDF 查看组件：固定 3x 高清渲染，支持缩放、拖动、旋转、重置。
 * 仅在首次加载/重置/切换文件时自适配窗口，不会覆盖用户缩放。
 */
export const MapPdfViewer: React.FC<MapPdfViewerProps> = ({
    pdfUrl,
    title = "地图 PDF 预览",
    pageNumber = 1,
    onClose,
    className = "",
    initialScale = 1,
}) => {
    const minScale = 0.2;
    const maxScale = 3;
    const containerRef = useRef<HTMLDivElement>(null);
    const dragStartRef = useRef<{ x: number; y: number } | null>(null);

    const [containerSize, setContainerSize] = useState<{ width: number; height: number }>({
        width: 0,
        height: 0,
    });
    const [pageSize, setPageSize] = useState<{ width: number; height: number } | null>(null);
    const [scale, setScale] = useState(1);
    const [rotation, setRotation] = useState(0);
    const [offset, setOffset] = useState({ x: 0, y: 0 });
    const [dragging, setDragging] = useState(false);
    const [numPages, setNumPages] = useState<number>();
    const [error, setError] = useState<string | null>(null);
    const [pageRenderSize, setPageRenderSize] = useState<{ width: number; height: number } | null>(null);
    const [activeGrid, setActiveGrid] = useState<{ row: number; col: number } | null>(null);
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

    const handleWheel = useCallback(
        (e: React.WheelEvent<HTMLDivElement>) => {
            e.preventDefault();
            const step = e.deltaY > 0 ? -0.1 : 0.1;
            handleZoom(step);
        },
        [handleZoom]
    );

    const rotate = useCallback((deg: number) => {
        setRotation((prev) => {
            const next = prev + deg;
            return ((next % 360) + 360) % 360;
        });
    }, []);

    const calcFitScale = useCallback(() => {
        if (!pageSize || !containerSize.width || !containerSize.height) return null;
        const baseW = (containerSize.width || pageSize.width) * RENDER_MULTIPLIER;
        const baseH = baseW * (pageSize.height / pageSize.width);
        const widthScale = containerSize.width / baseW;
        const heightScale = containerSize.height / baseH;
        return clamp(Math.min(widthScale, heightScale), minScale, maxScale);
    }, [containerSize.height, containerSize.width, pageSize, minScale, maxScale]);

    const resetView = useCallback(() => {
        const fit = calcFitScale();
        const fitScale = fit ?? 1;
        setScale(fitScale);
        setRotation(0);
        setOffset(clampOffsetXY(0, 0, fitScale, { row: 1, col: 1 }));
        setActiveGrid({ row: 1, col: 1 });
        setHasFitted(true);
    }, [calcFitScale, clampOffsetXY]);

    // PDF 资源配置
    const fileConfig = useMemo(
        () =>
            ({
                url: pdfUrl,
                withCredentials: false,
            }) as const,
        [pdfUrl]
    );

    // 容器宽度驱动渲染宽度（按容器尺寸的 2x 渲染）
    const renderWidth = useMemo(() => {
        return containerSize.width ? containerSize.width * RENDER_MULTIPLIER : undefined;
    }, [containerSize.width]);

    const pageTransform = useMemo(
        () => `translate(${offset.x}px, ${offset.y}px)`,
        [offset.x, offset.y]
    );

    const centerToGridCell = useCallback(
        (row: number, col: number) => {
            if (!pageSize) return;

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

            // 非中心格：固定使用容器基准的 2x 尺寸，再计算偏移
            const baseW = (containerSize.width || pageSize.width) * RENDER_MULTIPLIER;
            const baseH = baseW * (pageSize.height / pageSize.width);
            const displayedWidth = baseW;
            const displayedHeight = baseH;
            let cellX = (col - 1) * (displayedWidth / 3);
            const cellY = (row - 1) * (displayedHeight / 3);

            setScale(1);
            setOffset(clampOffsetXY(-cellX, -cellY, 1, { row, col }));
            setActiveGrid({ row, col });
        },
        [pageSize, calcFitScale, clampOffsetXY, containerSize.width]
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
        resetView();
    }, [hasFitted, pageSize, containerSize.width, containerSize.height, resetView]);

    // 切换 PDF 时允许重新自适配
    useEffect(() => {
        setHasFitted(false);
    }, [pdfUrl]);

    return (
        <div
            className={`relative max-w-5xl w-full rounded-2xl border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900 ${className}`}
        >
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-700 gap-3">
                <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                    {title} {numPages ? `(共 ${numPages} 页)` : ""}
                </div>
                <div className="flex items-center gap-2 flex-1 justify-center">
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
                        className="hidden sm:grid grid-cols-3 grid-rows-3 gap-[2px] border border-emerald-200 bg-emerald-50 overflow-hidden dark:border-slate-600 dark:bg-slate-800/80"
                        style={{ width: "56px", height: "42px" }}
                    >
                        {[0, 1, 2].map((r) =>
                            [0, 1, 2].map((c) => {
                                const active = activeGrid?.row === r && activeGrid.col === c;
                                return (
                                    <button
                                        key={`${r}-${c}`}
                                        type="button"
                                        className={[
                                            "block w-full h-full p-0 m-0 leading-none text-transparent transition-colors flex items-center justify-center",
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
                    {onClose && (
                        <Button
                            type="button"
                            variant="ghost"
                            className="px-2 py-1 text-xs text-slate-500 hover:text-slate-800 dark:text-slate-300 dark:hover:text-white"
                            onClick={onClose}
                            aria-label="关闭"
                        >
                            <X className="w-4 h-4" />
                        </Button>
                    )}
                </div>
            </div>

            <div
                ref={containerRef}
                className="relative max-h-[80vh] min-h-[360px] bg-slate-950/80 overflow-hidden rounded-b-2xl flex items-center justify-center"
                onWheel={handleWheel}
            >
                <Document
                    file={fileConfig}
                    onLoadSuccess={(info) => {
                        setNumPages(info.numPages);
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
                                pageNumber={pageNumber}
                                width={renderWidth}
                                scale={scale}
                                rotate={rotation}
                                renderAnnotationLayer={false}
                                renderTextLayer={false}
                                className="shadow-lg"
                                onLoadSuccess={(page) => {
                                    const w = (page as any).originalWidth ?? page.width;
                                    const h = (page as any).originalHeight ?? page.height;
                                    if (!w || !h) return;
                                    setPageRenderSize({
                                        width: page.width ?? 0,
                                        height: page.height ?? 0,
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
                {error && (
                    <div className="absolute bottom-2 left-1/2 -translate-x-1/2 text-xs text-rose-300 text-center px-3 py-1 bg-rose-900/70 rounded-lg">
                        {error}
                    </div>
                )}
            </div>
        </div>
    );
};
