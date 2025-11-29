import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { instance as createVizInstance } from "@viz-js/viz";
import { supabase } from "../../../lib/supabaseClient";

const vizPromise = createVizInstance();
const SVG_TTL = 5 * 60 * 1000; // 5 minutes

type SvgCacheEntry = { svg: string; expiresAt: number };
type DotCacheEntry = { dot: string; expiresAt: number };

const svgCache = new Map<string, SvgCacheEntry>();
const dotCache = new Map<string, DotCacheEntry>();

export function DotRender({
    cardId,
    fileName,
    className = "",
}: {
    cardId: string;
    fileName: string;
    className?: string;
}) {
    const key = useMemo(() => (cardId && fileName ? `${cardId}/${fileName}` : ""), [cardId, fileName]);

    const [svg, setSvg] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState<boolean>(true);

    useEffect(() => {
        let active = true;
        async function load() {
            if (!key) {
                setError("缺少 cardId 或 fileName");
                setLoading(false);
                return;
            }

            const now = Date.now();
            const cachedSvg = svgCache.get(key);
            if (cachedSvg && cachedSvg.expiresAt > now) {
                setSvg(cachedSvg.svg);
                setLoading(false);
                return;
            }

            let dotText: string | null = null;
            const cachedDot = dotCache.get(key);
            if (cachedDot && cachedDot.expiresAt > now) {
                dotText = cachedDot.dot;
            }

            if (!dotText) {
                const { data: signed, error: signError } = await supabase.storage
                    .from("quizit_card_medias")
                    .createSignedUrl(key, 120);
                if (signError || !signed?.signedUrl) {
                    console.error("signed url error", signError);
                    setError("无法获取文件签名链接");
                    setLoading(false);
                    return;
                }
                const resp = await fetch(signed.signedUrl);
                if (!resp.ok) {
                    setError(`下载失败 (${resp.status})`);
                    setLoading(false);
                    return;
                }
                dotText = await resp.text();
                dotCache.set(key, { dot: dotText, expiresAt: now + SVG_TTL });
            }

            try {
                const viz = await vizPromise;
                const rendered = await viz.renderString(dotText, { format: "svg", engine: "dot" });
                if (!active) return;
                svgCache.set(key, { svg: rendered, expiresAt: now + SVG_TTL });
                setSvg(rendered);
            } catch (err) {
                console.error("render dot error", err);
                if (active) setError("渲染失败");
            } finally {
                if (active) setLoading(false);
            }
        }

        load();
        return () => {
            active = false;
        };
    }, [key]);

    if (loading) {
        return <div className="text-xs text-slate-500 dark:text-slate-400">正在加载…</div>;
    }

    if (error) {
        return <div className="text-xs text-red-600 dark:text-red-400">{error}</div>;
    }

    if (!svg) return null;

    const isDark =
        typeof document !== "undefined" &&
        document.documentElement.classList.contains("dark");

    const mergedClass = clsx(
        "rounded-md p-2",
        isDark ? "bg-slate-200" : "bg-slate-50",
        className
    );

    //const themedSvg = svg;

    return (
        <div
            className={mergedClass}
            dangerouslySetInnerHTML={{ __html: svg || "" }}
        />
    );
}
