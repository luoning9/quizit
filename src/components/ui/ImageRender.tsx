import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { supabase } from "../../../lib/supabaseClient";

const SIGNED_URL_TTL_SECONDS = 60 * 60 * 6; // 6 hours
const SIGNED_URL_CACHE_TTL_MS = 60 * 60 * 1000 * 3; // 3 hours

const signedUrlCache = new Map<string, { url: string; expiresAt: number }>();

export function ImageRender({
    cardId,
    fileName,
    className = "",
}: {
    cardId: string;
    fileName: string;
    className?: string;
}) {
    const storageKey = useMemo(
        () => (cardId && fileName ? `${cardId}/${fileName}` : ""),
        [cardId, fileName]
    );

    const [imageUrl, setImageUrl] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let active = true;

        async function load() {
            if (!storageKey) {
                setError("缺少 cardId 或 fileName");
                setLoading(false);
                return;
            }
            setLoading(true);
            setError(null);

            const now = Date.now();
            const cached = signedUrlCache.get(storageKey);
            if (cached && cached.expiresAt > now) {
                setImageUrl(cached.url);
                setLoading(false);
                return;
            }

            const { data, error: signError } = await supabase.storage
                .from("quizit_card_medias")
                .createSignedUrl(storageKey, SIGNED_URL_TTL_SECONDS);

            if (signError || !data?.signedUrl) {
                console.error("signed url error", signError);
                setError("无法获取文件签名链接");
                setLoading(false);
                return;
            }

            const ttl = Math.min(SIGNED_URL_CACHE_TTL_MS, SIGNED_URL_TTL_SECONDS * 1000);
            signedUrlCache.set(storageKey, { url: data.signedUrl, expiresAt: now + ttl });

            if (!active) return;
            setImageUrl(data.signedUrl);
            setLoading(false);
        }

        load();
        return () => {
            active = false;
        };
    }, [storageKey]);

    if (loading) {
        return <div className="text-xs text-slate-500 dark:text-slate-400">正在加载图片…</div>;
    }

    if (error) {
        return <div className="text-xs text-rose-600 dark:text-rose-400">{error}</div>;
    }

    if (!imageUrl) return null;

    return (
        <div
            className={clsx(
                "w-full flex justify-center items-center bg-slate-50 dark:bg-slate-800 rounded-md p-3",
                className
            )}
        >
            <img
                src={imageUrl}
                alt={fileName}
                className="max-h-[75vh] max-w-full object-contain rounded"
                loading="lazy"
                onError={() => setError("图片加载失败")}
            />
        </div>
    );
}
