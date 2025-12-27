import React, {useEffect, useRef, useState} from "react";
import {useNavigate} from "react-router-dom";
import {useParams} from "react-router-dom";
import {supabase} from "../../lib/supabaseClient";
import {Card} from "../components/ui/Card";
import {Button} from "../components/ui/Button";
import clsx from "clsx";
import {useTimer} from "../components/TimerContext";  // ← 新增，路径和 AppLayout 一致
import {DotRender} from "../components/ui/DotRender";
import {MapPdfViewer} from "../components/ui/MapPdfViewer";
import {ImageRender} from "../components/ui/ImageRender";
import { parseFront, parseBack, type UserAnswer } from "../../lib/quizFormat";
import { renderPrompt, renderAnswer } from "./quizRenderer";
import { differenceInSeconds } from "date-fns";
import { Image as ImageIcon, X as XIcon, LogOut, GitBranch, Map as MapIcon, Link } from "lucide-react";
import MarkdownText from "../components/MarkdownText";

interface CardStatsRow {
    card_id: string;
    review_count: number | null;
    correct_count: number | null;
    wrong_count: number | null;
    ease_factor: number | null;
    last_reviewed_at: string | null;
}

interface DeckFolderStatsRow {
    path: string;
    deck_count: number;
    total_items: number;
    total_ease_factor: number | null;
    is_deck: boolean;
}

function completionColor(percent: number) {
    const t = Math.max(0, Math.min(1, percent));

    // 紫: #6D28D9 (109, 40, 217)
    const r1 = 109, g1 = 40, b1 = 217;
    // 蓝: #3B82F6 (59, 130, 246)
    const r2 = 59, g2 = 130, b2 = 246;

    const r = Math.round(r1 + (r2 - r1) * t);
    const g = Math.round(g1 + (g2 - g1) * t);
    const b = Math.round(b1 + (b2 - b1) * t);

    return `rgb(${r}, ${g}, ${b})`;
}

function easeFactorToColor(ease_factor: number | null | undefined): string {
    if (!ease_factor) return "bg-neutral-500";

    if (ease_factor < 1.5) return "bg-purple-700";      // 太难
    if (ease_factor < 2.5) return "bg-orange-500";   // 有点难
    if (ease_factor < 3.5) return "bg-blue-500";     // 还行
    return "bg-green-600";                             // 很容易
}

type CardStatsMap = Record<string, CardStatsRow | undefined>;
// 媒体列表 map：cardId -> media list
type CardMediaMap = Record<string, { name: string; id?: string }[]>;
type CardBaseData = {
    id: string;
    front: string;
    back: string;
    deck_title: string;
    deck_description: string | null;
    deck_id: string;
};
type CardViewData = {
    mediaReady: boolean;
    frontClean: string;
    backClean: string;
    frontSchema: ReturnType<typeof parseFront> | null;
    backSchema: ReturnType<typeof parseBack> | null;
    footerText: string;
    frontMediaNames: string[];
    backMediaNames: string[];
    mediaNotes: Record<string, string>;
};

function getContentSizeClass(content: string): { sizeClass: string; alignClass: string } {
    const trimmed = content.trim();
    const lines = trimmed.split(/\r?\n/).filter((l) => l.trim() !== "");
    const lineCount = lines.length;
    const len = trimmed.length;

    if (lineCount > 10 || len > 300) return {
        sizeClass: "leading-relaxed",
        alignClass: "text-left items-start"
    };
    if (lineCount > 6 || len > 120) return {
        sizeClass: "text-lg leading-relaxed",
        alignClass: "text-left items-start"
    };
    if (lineCount > 2 || len > 60) return {
        sizeClass: "text-xl leading-relaxed",
        alignClass: "text-left items-start"
    };
    return {sizeClass: "text-2xl leading-relaxed", alignClass: "text-center items-center"};
}

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

function getHttpUrl(raw: string | null | undefined): string | null {
    const trimmed = raw?.trim();
    if (!trimmed) return null;
    try {
        const url = new URL(trimmed);
        if (url.protocol === "http:" || url.protocol === "https:") {
            return url.toString();
        }
    } catch {
        // ignore invalid URLs
    }
    return null;
}

function escapeRegExp(str: string): string {
    return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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

export function DeckPracticePage() {
    const navigate = useNavigate();
    const {deckName} = useParams();
    const decodedName = decodeURIComponent(deckName || "");
    // 每轮练习取多少张卡
    const CARD_THRESHOLD = 10;

    // 已完成题数（本轮）
    const [answersSinceBreak, setAnswersSinceBreak] = useState(0);

// 是否处于暂停/休息状态
    const [isBreak, setIsBreak] = useState(false);
    const [cardBaseMap, setCardBaseMap] = useState<Record<string, CardBaseData>>({});
    const [cardIds, setCardIds] = useState<string[]>([]);

    // 一个统一的 loading 状态就够了
    const [loading, setLoading] = useState(true);

    const [index, setIndex] = useState(0);
    const [showBack, setShowBack] = useState(false);
    const frontRef = useRef<HTMLDivElement | null>(null);
    const backRef = useRef<HTMLDivElement | null>(null);
    const dividerRef = useRef<HTMLDivElement | null>(null);
    const [mediaModal, setMediaModal] = useState<{ cardId: string; name: string } | null>(null);
    const [hoverInfo, setHoverInfo] = useState<string>("点击显示背面");

    const [folderStats, setFolderStats] = useState<DeckFolderStatsRow | null>(null);

    // 新增：当前用户这组卡片的 stats 映射
    const [cardStatsMap, setCardStatsMap] = useState<CardStatsMap>({});
    // 媒体列表映射
    const [cardMediaMap, setCardMediaMap] = useState<CardMediaMap>({});
    // 视图派生数据
    const [cardViewMap, setCardViewMap] = useState<Record<string, CardViewData>>({});
    const [reloadKey, setReloadKey] = useState(0);

    useEffect(() => {
        async function loadPracticeCards() {
            setLoading(true);
            setIsBreak(false);
            setAnswersSinceBreak(0);

            try {
                // 先读 user_deck_folder_view 当前节点的数据
                if (decodedName) {
                    const {data: statsRow, error: statsError} = await supabase
                        .from("user_deck_folder_view")
                        .select("path, deck_count, total_items, total_ease_factor, is_deck")
                        .eq("path", decodedName)
                        .maybeSingle();

                    if (statsError) {
                        console.error("load user_deck_folder_view error", statsError);
                    } else {
                        setFolderStats(statsRow as DeckFolderStatsRow);
                    }
                } else {
                    setFolderStats(null);
                }
                const {data, error} = await supabase.rpc("select_practice_cards_leitner", {
                    _folder_path: decodedName || "", // 当前目录/卡组路径
                    _limit: CARD_THRESHOLD,                      // 一次抽多少张卡，先写死也行
                    _mode: "ordered",                 // "random" | "ordered"
                });

                if (error) {
                    console.error("select_practice_cards error", error);
                    setCardIds([]);
                    setCardBaseMap({});
                    setCardMediaMap({});
                    setCardViewMap({});
                    setLoading(false);
                    return;
                }

                const rows =
                    (data as {
                        card_id: string;
                        deck_id: string;
                        deck_title: string;
                        deck_description: string | null;
                        front: string;
                        back: string;
                    }[]) || [];

                if (rows.length === 0) {
                    setCardIds([]);
                    setCardBaseMap({});
                    setCardMediaMap({});
                    setCardViewMap({});
                    setLoading(false);
                    return;
                }

                const ids: string[] = [];
                const baseMap: Record<string, CardBaseData> = {};

                for (const r of rows) {
                    ids.push(r.card_id);
                    baseMap[r.card_id] = {
                        id: r.card_id,
                        front: r.front,
                        back: r.back,
                        deck_title: r.deck_title,
                        deck_description: r.deck_description ?? null,
                        deck_id: r.deck_id,
                    };
                }

                setCardIds(ids);
                setCardBaseMap(baseMap);
                setCardMediaMap({});
                setCardViewMap({});
                // 每次重新抽卡，重置索引和正反面
                setIndex(0);
                setShowBack(false);
                setHoverInfo("点击显示背面");
                cardStartTimeRef.current = new Date();
            } finally {
                setLoading(false);
            }
        }

        loadPracticeCards();
    }, [decodedName, reloadKey]);

    // 记录所抽取卡片的ease_factor之和
    const totalEaseFactorOfCards = useRef(0);
    const cardStartTimeRef = useRef<Date | null>(null);

    // 3. 加载当前用户对这些卡片的 card_stats
    useEffect(() => {
        async function loadStats() {
            //const { data: userData } = await supabase.auth.getUser();
            //const user = userData.user;
            //if (!user) return;
            if (cardIds.length === 0) return;

            //const ids = cardIds;

            const {data, error} = await supabase
                .from("card_stats")
                .select("card_id, review_count, correct_count, wrong_count, ease_factor, last_reviewed_at")
                .gt("review_count", 0)
                .in("card_id", cardIds);

            if (!error && data) {
                let sum = 0
                const map: CardStatsMap = {};
                data.forEach((row: CardStatsRow) => {
                    map[row.card_id] = row as CardStatsRow;
                    //console.log(`==${row.card_id}==${row.ease_factor}`);
                    sum += Number(row.ease_factor ?? 0);
                });
                totalEaseFactorOfCards.current = sum;
                setCardStatsMap(map);
            }
        }

        loadStats();
        cardStartTimeRef.current = new Date();
    }, [cardIds]);
    // 基础派生：front/back 文本与 schema
    useEffect(() => {
        const updates: Record<string, CardViewData> = {};
        for (const cid of cardIds) {
            const base = cardBaseMap[cid];
            if (!base) continue;
            const existing = cardViewMap[cid];
            if (existing) continue;

            const frontClean = trimEmptyLines(base.front);
            const backClean = trimEmptyLines(base.back);
            const parsedBack = parseBack(base.back, true);
            updates[cid] = {
                mediaReady: false,
                frontClean,
                backClean,
                frontSchema: parseFront(base.front),
                backSchema: parsedBack,
                footerText: parsedBack?.footer ?? "",
                frontMediaNames: [],
                backMediaNames: [],
                mediaNotes: {},
            };
            //console.log(`set base to ${cid}`)
        }
        if (Object.keys(updates).length === 0) return;
        setCardViewMap((prev) => ({...prev, ...updates}));
    }, [cardIds, cardBaseMap, cardViewMap]);
    // 媒体派生：front/back 媒体列表
    useEffect(() => {
        const updates: Record<string, CardViewData> = {};
        for (const cid of cardIds) {
            const mediaList = cardMediaMap[cid] ?? [];
            const existing = cardViewMap[cid];
            if (!existing || existing.mediaReady) continue;

            const frontMediaNames = mediaList.filter((m) => m.name.startsWith("front.")).map((m) => m.name);
            const backMediaNames = mediaList.filter((m) => m.name.startsWith("back")).map((m) => m.name);
            const backNotes = extractNotesFromContent(existing.footerText);
            const mediaNotes: Record<string, string> = {};
            backMediaNames.forEach((name, idx) => {
                const lower = name.toLowerCase();
                if (lower.endsWith(".png") || lower.endsWith(".jpg") || lower.endsWith(".jpeg")) {
                    mediaNotes[name] = backNotes[idx] ?? "";
                }
            });

            //const needUpdate = (frontMediaNames.length + backMediaNames.length > 0);
            if (frontMediaNames.length + backMediaNames.length <= 0) continue;
            //console.log(`set media to ${cid}`)
            /* 计算mediaNotes */

            updates[cid] = {
                ...(existing),
                frontMediaNames,
                backMediaNames,
                mediaNotes: Object.keys(mediaNotes).length ? mediaNotes : existing.mediaNotes ?? {},
                mediaReady: true,
            };
        }
        //console.log(updates);
        if (Object.keys(updates).length === 0) return;
        setCardViewMap((prev) => ({...prev, ...updates}));
    }, [cardIds, cardMediaMap, cardViewMap]);
    // 异步加载媒体列表（不阻塞抽卡）
    useEffect(() => {
        let cancelled = false;
        async function loadMedias() {
            if (cardIds.length === 0) {
                if (Object.keys(cardMediaMap).length > 0) {
                    setCardMediaMap({});
                }
                return;
            }
            const missing = cardIds.filter((cid) => !(cardMediaMap[cid]));
            if (missing.length === 0) return;
            //console.warn(missing);
            const results: CardMediaMap = {};
            await Promise.all(
                missing.map(async (cid) => {
                    try {
                        const {data: list, error: listErr} = await supabase
                            .storage
                            .from("quizit_card_medias")
                            .list(`${cid}`);
                        if (!listErr && list && list.length > 0) {
                            const typedList = list as { name: string; id?: string }[];
                            results[cid] = typedList.map((f) => ({name: f.name, id: f.id}));
                        } else {
                            results[cid] = [];
                        }
                    } catch (e) {
                        console.error(e);
                        results[cid] = [];
                    }
                })
            );

            if (cancelled) return;
            if (Object.keys(results).length > 0) {
                setCardMediaMap((prev) => ({...prev, ...results}));
            }
        }
        loadMedias();
        return () => {
            cancelled = true;
        };
    }, [cardIds, cardMediaMap]);
    // 计时器：全局顶栏那个
    const {reset, start, pause} = useTimer();
    useEffect(() => {
        reset()
        // 离开页面：暂停计时器
        return () => {
            pause();
        };
        // 我们就是想只在挂载/卸载时触发一次，所以依赖用 []
    }, []);
// ② isBreak 控制计时器运行/暂停
    useEffect(() => {
        if (isBreak) {
            pause();   // 看答案 → 暂停计时
        } else {
            start();   // 做题阶段 → 开始计时
        }
    }, [isBreak, start, pause]);


    // 3. 切题 / 翻面
    const nextCard = () => {
        if (cardIds.length === 0) return;
        if (showBack) flip();
        //setShowBack(false);
        //if (backRef.current) backRef.current.classList.add("hidden");
        setIndex((i) => i+1<cardIds.length?i+1:i);
    };

    const flip = () => {
        //const front = frontRef.current;
        const back = backRef.current;
        const divider = dividerRef.current;

        const currentlyHidden = back ? back.classList.contains("hidden") : true;

        if (currentlyHidden) {
            // 显示背面，并滚动到分割线附近
            if (back) back.classList.remove("hidden");
            if (divider) divider.classList.remove("hidden");
            setShowBack(true);
            setHoverInfo("点击隐藏背面");
            window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
        } else {
            // 隐藏背面，回到顶部
            if (back) back.classList.add("hidden");
            if (divider) divider.classList.add("hidden");
            setShowBack(false);
            setHoverInfo("点击显示背面");
        }
    };

    // 4. 记录掌握程度（写入 card_stats 和 card_reviews，并自动下一题）
    async function recordDifficulty(level: number) {
        // 拍下当前卡片（快照）
        const currentCardId = cardIds[index];
        const currentCard = currentCardId ? cardBaseMap[currentCardId] : null;
        if (!currentCard) return;

        // UI 立即跳到下一张卡并回到正面
        nextCard();

        // 后台写数据库
        const {data: userData} = await supabase.auth.getUser();
        const user = userData.user;

        if (!user) return;

        const easeMap: Record<number, number> = {
            1: 1.0,
            2: 2.0,
            3: 3.0,
            4: 4.0
        };
        const ease_factor = easeMap[level] ?? 2.0;

        const user_id = user.id;
        const card_id = currentCard.id;
        const now = new Date().toISOString();
        const startAt = cardStartTimeRef.current;
        const timeSpentSeconds =
            startAt && !Number.isNaN(startAt.getTime())
                ? Math.max(0, differenceInSeconds(new Date(), startAt))
                : null;
        cardStartTimeRef.current = new Date();

        const is_correct = ease_factor >2;

        // ------- 1) 记录 card_reviews（一条记录就插入一次） -------
        await supabase.from("card_reviews").insert({
            card_id,
            reviewed_at: now,
            user_answer: null,         // 你目前没有输入作答内容
            is_correct: is_correct,          // 没有对错概念，写 null
            time_spent: timeSpentSeconds,
            belongs_to: currentCard.deck_id ?? null,
            is_question: false,
            meta: {difficulty: ease_factor} // 把点击难度记在 meta 里
        });

        // ------- 2) 更新 card_stats（累积统计） -------
        const {data: existing} = await supabase
            .from("card_stats")
            .select("*")
            .eq("user_id", user_id)
            .eq("card_id", card_id)
            .maybeSingle();

        if (!existing) {
            await supabase.from("card_stats").insert({
                user_id,
                card_id,
                review_count: 1,
                correct_count: is_correct ? 1 : 0,
                wrong_count: is_correct ? 0 : 1,
                ease_factor,
                last_reviewed_at: now
            });
            // 本地也更新一下 map
            setCardStatsMap((prev) => ({
                ...prev,
                [card_id]: {
                    card_id,
                    review_count: 1,
                    correct_count: is_correct ? 1 : 0,
                    wrong_count: is_correct ? 0 : 1,
                    ease_factor,
                    last_reviewed_at: now,
                },
            }));
        } else {
            const newReviewCount = (existing.review_count || 0) + 1;
            const newCorrectCount = is_correct ? ((existing.correct_count || 0) + 1) : 0;
            const newWrongCount = is_correct ? 0 : ((existing.wrong_count || 0) + 1);
            await supabase
                .from("card_stats")
                .update({
                    review_count: newReviewCount,
                    correct_count: newCorrectCount,
                    wrong_count: newWrongCount,
                    ease_factor,
                    last_reviewed_at: now
                })
                .eq("id", existing.id);
            setCardStatsMap((prev) => ({
                ...prev,
                [card_id]: {
                    card_id,
                    review_count: newReviewCount,
                    correct_count: newCorrectCount,
                    wrong_count: newWrongCount,
                    ease_factor,
                    last_reviewed_at: now,
                },
            }));
        }
        setAnswersSinceBreak((prev) => {
            const next = prev + 1;

            if (next >= CARD_THRESHOLD || next >= cardIds.length ) {
                setIsBreak(true);   // 进入休息模式
            }

            return next;
        });
    }

    // 5. 状态渲染
    if (loading) return <div>正在抽取练习卡片…</div>;
    if (!deckName) return <div className="text-sm text-slate-500">未找到该题库或目录。</div>;
    if (cardIds.length === 0) return <div className="text-sm text-slate-500">当前目录下暂无可练习的卡片。</div>;

    const currentId = cardIds[Math.min(index, cardIds.length - 1)];
    const current = cardBaseMap[currentId];
    const currentView = cardViewMap[currentId];
    const currentStats = cardStatsMap[currentId];
    if (!current) return <div className="text-sm text-slate-500">未找到该卡片。</div>;
    if (!currentView) return <div className="text-sm text-slate-500">正在准备卡片内容…</div>;
    const descriptionUrl = getHttpUrl(current.deck_description);
    const openDeckApp = () => {
        if (!descriptionUrl) return;
        const newWindow = window.open(descriptionUrl, "deck-app");
        if (newWindow) {
            newWindow.opener = null;
        }
    };

    //    const difficultyLevel = currentStats?.ease_factor;
    const reviewCount = currentStats?.review_count ?? 0;
    const completionRatio = (() => {
        if (cardIds.length === 0) return 0;

        let total = 0;
        for (const cid of cardIds) {
            const stats = cardStatsMap[cid];
            const level = stats?.ease_factor ?? 0;
            total += level;
        }
        return (total + (folderStats?.total_ease_factor ?? 0) - totalEaseFactorOfCards.current)
            / ((folderStats?.total_items ?? 0) * 4);
    })();
    const completionText = (completionRatio * 100).toFixed(0) + "%";

    const {sizeClass: frontSizeClass, alignClass: frontAlign} = getContentSizeClass(currentView.frontClean);
    const {sizeClass: backSizeClass, alignClass: backAlign} = getContentSizeClass(currentView.backClean);
    const isDarkMode =
        typeof document !== "undefined" &&
        document.documentElement.classList.contains("dark");
    const ringBgColor = isDarkMode ? "#1f2937" : "#e2e8f0";
    const footerForRender = (() => {
        if (!currentView.footerText) return "";
        let cleaned = currentView.footerText;
        const notes = currentView.mediaNotes ? Object.values(currentView.mediaNotes).filter(Boolean) : [];
        for (const note of notes) {
            const pattern = new RegExp(`!\\[${escapeRegExp(note)}\\]`, "g");
            cleaned = cleaned.replace(pattern, "");
        }
        return cleaned.trim();
    })();

    if (isBreak) {
        return (
            <BreakScreen
                answers={answersSinceBreak}
                onContinue={() => setReloadKey((k) => k + 1)}
                onFinish={() => navigate(`/?path=${encodeURIComponent(deckName)}`)}
            />
        );
    }

    return (
        <div className="space-y-6">
            <div className="mb-4 flex items-center justify-start gap-6">
                {/* 左：标题 */}
                <div>
                    <h1 className="text-xl font-semibold">{deckName}</h1>
                    <div className="text-xs text-slate-500 mt-1">
                        <span>第 {answersSinceBreak} / {cardIds.length} /{folderStats?.total_items} 张 </span>

                    </div>
                </div>
                {/* 中间：一排圆点，每个表示一张卡片 */}
                <div className="w-[30rem] md:w-[34rem] mt-1 flex flex-wrap items-center justify-center gap-4">
                    <div className="w-4"></div>
                    {cardIds.map((cid, idx) => {
                        const stats = cardStatsMap[cid];
                        const isCurrent = idx === index;              // 当前卡

                        const difficultyLevel = stats?.ease_factor ?? 0;   // 1~4 或 0 未练过

                        const glowRingColors: Record<number, string> = {
                            1: "ring-purple-400",
                            2: "ring-orange-400",
                            3: "ring-blue-400",
                            4: "ring-green-400",
                        };

                        const colorClass = easeFactorToColor(difficultyLevel) // 未练过 = 灰色
                        const glowClass =
                            difficultyLevel >= 1 && difficultyLevel <= 4
                                ? glowRingColors[difficultyLevel]
                                : "ring-neutral-300"; // 兜底发光颜色

                        return (
                            <div className="w-[24px] flex justify-center" key={cid}>
                                <div
                                    className={clsx(
                                        "h-3 w-3 rounded-full transition-all",
                                        colorClass,
                                        isCurrent && [
                                            "scale-125",                 // ★ 当前卡片变大
                                            "ring-1 ring-offset-2 ring-offset-transparent",
                                            glowClass,   // ★ 发光颜色
                                        ]
                                    )}
                                />
                            </div>
                        );
                    })}
                </div>
                <div
                    className="relative w-16 h-16 rounded-full flex items-center justify-center bg-slate-200 dark:bg-slate-800"
                    style={{
                        background: `conic-gradient(
      var(--ring-color) ${completionRatio * 360}deg,
      var(--ring-bg) 0deg
    )`,
                        '--ring-color': completionColor(completionRatio),
                        '--ring-bg': ringBgColor,
                    } as React.CSSProperties}
                >
                    <div
                        className="absolute w-10 h-10 rounded-full flex items-center justify-center text-xs bg-white text-slate-800 dark:bg-slate-700 dark:text-slate-50 shadow-sm">
                        {completionText}
                    </div>
                </div>
                <Button
                    variant="ghost"
                    className="w-20 ml-4 px-3 py-2"
                    onClick={() => navigate(`/?path=${deckName}`)}
                    title="退出到目录"
                >
                    <LogOut className="w-8 h-8" aria-hidden />

                </Button>
            </div>

            {/* 主区域：闪卡 */}
            <div className="flex items-center justify-center gap-1 mt-4">
                <Card
                    className={clsx(
                        "w-[38rem] md:w-[42rem]",
                        "group cursor-pointer select-none",
                        "p-0 border border-slate-300 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-900/50 dark:shadow-[0_16px_36px_-14px_rgba(0,0,0,0.7)]"
                    )}>
                    {/* ✅ 顶部状态栏：难度 + 练习次数 */}
                    <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-300 mb-0">
                        {/* 难度颜色条 */}
                        <div className="flex-1 mr-3 flex items-center gap-2 min-w-0">
                            <span className="truncate">{current.deck_title}</span>
                            {descriptionUrl && (
                                <button
                                    type="button"
                                    className="text-slate-500 hover:text-emerald-600 dark:text-slate-300 dark:hover:text-sky-300"
                                    title="访问相关app"
                                    onClick={openDeckApp}
                                >
                                    <Link className="w-3.5 h-3.5 flex-shrink-0" />
                                </button>
                            )}
                        </div>

                        {/* 练习次数 */}
                        <div className="text-xs text-slate-500 dark:text-slate-300 whitespace-nowrap">
                            练习次数：{reviewCount}
                        </div>
                    </div>
                    {/* 卡片内容 */}
                    <div className="relative w-full h-full min-h-[52vh] flex flex-col group">
                        {/* 正反面区域 */}
                        <div
                            className="mt-2 flex-1 min-h-0 flex flex-col justify-start items-stretch cursor-pointer gap-3"
                            onClick={flip}
                            onMouseEnter={() => setHoverInfo(showBack ? "点击隐藏背面" : "点击显示背面")}
                            onMouseLeave={() => setHoverInfo("...")}
                            role="button"
                            aria-label={showBack ? "查看题目" : "查看答案"}
                        >
                            {/* 卡片正面 */}
                            <div
                                className={clsx(
                                    "min-h-[30vh] flex flex-col gap-2 justify-center whitespace-pre-line",
                                    frontSizeClass,
                                    frontAlign,
                                )}
                                ref={frontRef}
                            >
                                {currentView.frontMediaNames
                                    .filter((n) => getMediaType(n))
                                    .map((name) => {
                                        const mediaType = getMediaType(name);
                                        const lower = name.toLowerCase();
                                        const Icon =
                                            mediaType === "dot"
                                                ? GitBranch
                                                : mediaType === "map"
                                                    ? MapIcon
                                                    : ImageIcon;
                                        return (
                                            <button
                                                key={name}
                                            className="w-full flex justify-center items-center gap-2 text-sm text-blue-600 dark:text-blue-300 underline"
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                setMediaModal({ cardId: current.id, name });
                                            }}
                                            onMouseEnter={() => setHoverInfo(currentView.mediaNotes?.[name] || `查看媒体：${name}`)}
                                            onMouseLeave={() => setHoverInfo(showBack ? "点击隐藏背面" : "点击显示背面")}
                                            title={currentView.mediaNotes?.[name] || `查看媒体 (${name})`}
                                        >
                                                <Icon className="h-8 w-8" aria-hidden />
                                                <span className="sr-only">
                                                    {lower.endsWith(".dot") ? "查看图示" : "查看媒体"}
                                                </span>
                                            </button>
                                        );
                                    })}
                                {currentView.frontSchema
                                    ? renderPrompt(currentView.frontSchema, {
                                        userAnswer: [] as UserAnswer,
                                        setUserAnswer: undefined,
                                        disabled: true,
                                    })
                                    : currentView.frontClean}
                            </div>
                            {/* 卡片背面（始终显示） */}
                            <div
                                ref={dividerRef}
                                className="hidden h-[2px] w-full bg-slate-300 dark:bg-slate-600 border-t border-slate-400 dark:border-slate-500"
                            />
                            <div
                                className={clsx(
                                    "hidden flex flex-col gap-2 justify-start whitespace-pre-line",
                                    backSizeClass,
                                    backAlign,
                                )}
                                ref={backRef}
                            >
                                {currentView.backMediaNames.length > 0 && (
                                    <div className="flex flex-wrap items-center gap-2">
                                        {currentView.backMediaNames
                                            .filter((n) => getMediaType(n))
                                            .map((name) => {
                                                const mediaType = getMediaType(name);
                                                const Icon =
                                                    mediaType === "dot"
                                                        ? GitBranch
                                                        : mediaType === "map"
                                                            ? MapIcon
                                                            : ImageIcon;
                                                return (
                                                    <button
                                                        key={name}
                                                        className="flex items-center gap-1 text-sm text-blue-600 dark:text-blue-300 underline"
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            setMediaModal({ cardId: current.id, name });
                                                        }}
                                                        title={currentView.mediaNotes?.[name] || `查看媒体 (${name})`}
                                                    >
                                                        <Icon
                                                            className={clsx(
                                                                "h-5 w-5",
                                                                mediaType === "dot"
                                                                    ? "text-emerald-500"
                                                                    : mediaType === "map"
                                                                        ? "text-sky-500"
                                                                        : "text-blue-500"
                                                            )}
                                                        />
                                                        <span>{name}</span>
                                                    </button>
                                                );
                                            })}
                                    </div>
                                )}
                                {currentView.frontSchema && currentView.backSchema
                                    ? renderAnswer(currentView.frontSchema, currentView.backSchema)
                                    : currentView.backClean}
                                {footerForRender && (
                                    <div className="mt-0 pt-1 border-t border-slate-200 dark:border-slate-700 text-base text-slate-700 dark:text-slate-200">
                                        <MarkdownText content={footerForRender} />
                                    </div>
                                )}
                                {/* JSON.stringify(frontSchema) */}
                            </div>
                        </div>
                        {hoverInfo && (
                            <button
                                type="button"
                                onClick={flip}
                                className="mt-auto w-full text-center opacity-70 transition-opacity duration-200 pb-0 text-base text-slate-500 dark:text-slate-300 hover:opacity-100"
                            >
                                {hoverInfo}
                            </button>
                        )}
                    </div>
                </Card>
            </div>
            {mediaModal && (
                <div
                    className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
                    onClick={() => setMediaModal(null)}
                >
                    <div
                        className="bg-white dark:bg-slate-900 rounded-lg shadow-2xl max-w-5xl w-full max-h-[95vh] overflow-auto p-4"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="flex justify-between items-center mb-3">
                            <div className="text-sm text-slate-600 dark:text-slate-300">
                                {mediaModal.name}
                            </div>
                            <button
                                className="flex items-center gap-1 text-sm text-blue-600 dark:text-blue-300 underline"
                                onClick={() => setMediaModal(null)}
                            >
                                <XIcon className="h-4 w-4" />
                                关闭
                            </button>
                        </div>
                        {getMediaType(mediaModal.name) === "dot" ? (
                            <DotRender
                                cardId={mediaModal.cardId}
                                fileName={mediaModal.name}
                                className="w-full"
                            />
                        ) : getMediaType(mediaModal.name) === "map" ? (
                            <MapPdfViewer
                                cardId={mediaModal.cardId}
                                filename={mediaModal.name}
                                className="w-full"
                            />
                        ) : getMediaType(mediaModal.name) === "image" ? (
                            <ImageRender
                                cardId={mediaModal.cardId}
                                fileName={mediaModal.name}
                                className="w-full"
                            />
                        ) : (
                            <div className="text-sm text-rose-500">
                                暂不支持的文件类型：{mediaModal.name}
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* 一排四个掌握程度按钮 */}
            {showBack && (
                <div className="flex justify-center gap-5 mt-1 w-full">
                    <Button variant="none"
                            onClick={() => recordDifficulty(1)}
                            className="bg-purple-700 hover:bg-purple-800 text-slate-100 px-4 py-2 rounded font-normal"
                    >
                        太难了
                    </Button>

                    <Button variant="none"
                            onClick={() => recordDifficulty(2)}
                            className="bg-orange-500 hover:bg-orange-600 text-slate-100 px-4 py-2 rounded font-normal"
                    >
                        有点难
                    </Button>

                    <Button variant="none"
                            onClick={() => recordDifficulty(3)}
                            className="bg-blue-500 hover:bg-blue-600 text-slate-100 px-4 py-2 rounded font-normal"
                    >
                        还行吧
                    </Button>

                    <Button variant="none"
                            onClick={() => recordDifficulty(4)}
                            className="bg-green-600 hover:bg-green-700 text-slate-100 px-4 py-2 rounded font-normal"
                    >
                        很容易
                    </Button>
                </div>
            )}
        </div>
    );
}


function BreakScreen({
                         answers,
                         onContinue,
                         onFinish,
                     }: {
    answers: number;
    onContinue: () => void;
    onFinish: () => void;
}) {
    return (
        <div className="w-full flex flex-col items-center justify-center py-12">
            <div className="text-3xl font-bold text-white mb-6">休息一下 👋</div>

            <div className="text-slate-300 mb-8">
                本轮你已学习 <span className="font-semibold">{answers}</span> 张卡片
            </div>

            <div className="flex gap-4">
                <Button
                    variant="primary"
                    className="w-32 px-6 py-3 rounded-2xl text-lg font-semibold"
                    onClick={onContinue}
                >
                    继续练习
                </Button>

                <Button
                    variant="outline"
                    className="w-32 px-6 py-3 rounded-2xl text-lg text-slate-100 border-slate-600 hover:bg-slate-800"
                    onClick={onFinish}
                >
                    结束
                </Button>
            </div>
        </div>
    );
}
