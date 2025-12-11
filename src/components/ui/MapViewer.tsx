import React, { useCallback, useMemo, useState } from "react";
import { X, Plus, Minus, RotateCcw, RotateCw, RefreshCw } from "lucide-react";
import { Button } from "./Button.tsx";

interface MapViewerProps {
    imageUrl: string;
    alt?: string;
    title?: string;
    onClose?: () => void;
    className?: string;
    initialScale?: number;
    minScale?: number;
    maxScale?: number;
}

const clamp = (value: number, min: number, max: number) =>
    Math.min(max, Math.max(min, value));

/**
 * 地图查看窗口：展示一张图片，支持缩放、90 度旋转，方便在弹窗中复用。
 */
export const MapViewer: React.FC<MapViewerProps> = ({
    imageUrl,
    alt = "map",
    title = "地图预览",
    onClose,
    className = "",
    initialScale = 1,
    minScale = 0.4,
    maxScale = 4,
}) => {
    const [scale, setScale] = useState(initialScale);
    const [rotation, setRotation] = useState(0);

    const handleZoom = useCallback(
        (delta: number) => {
            setScale((prev) => clamp(prev + delta, minScale, maxScale));
        },
        [minScale, maxScale]
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
            // 让角度保持在 0-359 之间，方便计算
            return ((next % 360) + 360) % 360;
        });
    }, []);

    const resetView = useCallback(() => {
        setScale(initialScale);
        setRotation(0);
    }, [initialScale]);

    const transformStyle = useMemo(
        () => ({
            transform: `scale(${scale}) rotate(${rotation}deg)`,
        }),
        [scale, rotation]
    );

    return (
        <div
            className={`relative max-w-5xl w-full rounded-2xl border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900 ${className}`}
        >
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-700">
                <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                    {title}
                </div>
                <div className="flex items-center gap-2">
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
                className="relative max-h-[80vh] min-h-[360px] bg-slate-950/80 overflow-hidden rounded-b-2xl flex items-center justify-center"
                onWheel={handleWheel}
            >
                <div className="select-none">
                    <img
                        src={imageUrl}
                        alt={alt}
                        className="max-h-[80vh] max-w-full object-contain transition-transform duration-150 ease-out"
                        style={transformStyle}
                        draggable={false}
                    />
                </div>
            </div>
        </div>
    );
};
