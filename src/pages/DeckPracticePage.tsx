import React, {useEffect, useRef, useState} from "react";
import { useNavigate } from "react-router-dom";
import { useParams } from "react-router-dom";
import { supabase } from "../../lib/supabaseClient";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import clsx from "clsx";
import { useTimer } from "../components/TimerContext";  // ← 新增，路径和 AppLayout 一致

interface CardData {
    id: string;
    front: string;
    back: string;
    deck_title: string;
}

interface CardStatsRow {
    card_id: string;
    review_count: number | null;
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
    if (ease_factor < 2.5)  return "bg-orange-500";   // 有点难
    if (ease_factor < 3.5)  return "bg-green-600";     // 还行
    return "bg-blue-500";                             // 很容易
}
type CardStatsMap = Record<string, CardStatsRow | undefined>;

function getContentSizeClass(content: string): { sizeClass: string; alignClass: string } {
    const trimmed = content.trim();
    const lines = trimmed.split(/\r?\n/).filter((l) => l.trim() !== "");
    const lineCount = lines.length;
    const len = trimmed.length;

    if (lineCount > 10 || len > 600) return { sizeClass: "text-sm leading-relaxed", alignClass: "text-left items-start" };
    if (lineCount > 6 || len > 300) return { sizeClass: "text-base leading-relaxed", alignClass: "text-left items-start" };
    return { sizeClass: "text-lg leading-relaxed", alignClass: "text-center items-center" };
}

function trimEmptyLines(content: string): string {
    const lines = content.split(/\r?\n/);
    while (lines.length && !lines[0].trim()) lines.shift();
    while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
    return lines.join("\n");
}

export function DeckPracticePage() {
    const navigate = useNavigate();
    const { deckName } = useParams();
    const decodedName = decodeURIComponent(deckName || "");
    // 每轮练习取多少张卡
    const CARD_THRESHOLD = 10;

    // 已完成题数（本轮）
    const [answersSinceBreak, setAnswersSinceBreak] = useState(0);

// 是否处于暂停/休息状态
    const [isBreak, setIsBreak] = useState(false);
    //const [deckTitle, setDeckTitle] = useState("");
    const [cards, setCards] = useState<CardData[]>([]);

    // 一个统一的 loading 状态就够了
    const [loading, setLoading] = useState(true);

    const [index, setIndex] = useState(0);
    const [showBack, setShowBack] = useState(false);

    const [folderStats, setFolderStats] = useState<DeckFolderStatsRow | null>(null);

    // 新增：当前用户这组卡片的 stats 映射
    const [cardStatsMap, setCardStatsMap] = useState<CardStatsMap>({});
    const [reloadKey, setReloadKey] = useState(0);
    useEffect(() => {
        async function loadPracticeCards() {
            setLoading(true);
            setIsBreak(false);
            setAnswersSinceBreak(0);

            try {
                // 先读 deck_folder_stats 当前节点的数据
                if (decodedName) {
                    const { data: statsRow, error: statsError } = await supabase
                        .from("deck_folder_stats")
                        .select("path, deck_count, total_items, total_ease_factor, is_deck")
                        .eq("path", decodedName)
                        .maybeSingle();

                    if (statsError) {
                        console.error("load deck_folder_stats error", statsError);
                    } else {
                        setFolderStats(statsRow as DeckFolderStatsRow);
                    }
                } else {
                    setFolderStats(null);
                }
                const { data, error } = await supabase.rpc("select_practice_cards", {
                    _folder_path: decodedName || "", // 当前目录/卡组路径
                    _limit: CARD_THRESHOLD,                      // 一次抽多少张卡，先写死也行
                    _mode: "random",                 // "random" | "ordered" | "reverse"
                });

                if (error) {
                    console.error("select_practice_cards error", error);
                    setCards([]);
                    setLoading(false);
                    return;
                }

                const rows =
                    (data as {
                        card_id: string;
                        deck_id: string;
                        deck_title: string;
                        front: string;
                        back: string;
                    }[]) || [];

                if (rows.length === 0) {
                    setCards([]);
                    setLoading(false);
                    return;
                }

                // 用 RPC 返回的卡片填充 CardData[]
                setCards(
                    rows.map((r) => ({
                        id: r.card_id,
                        front: r.front,
                        back: r.back,
                        deck_title: r.deck_title,
                    }))
                );
                // 每次重新抽卡，重置索引和正反面
                setIndex(0);
                setShowBack(false);
            } finally {
                setLoading(false);
            }
        }

        loadPracticeCards();
    }, [decodedName, reloadKey]);

    // 记录所抽取卡片的ease_factor之和
    const totalEaseFactorOfCards = useRef(0);

    // 3. 加载当前用户对这些卡片的 card_stats
    useEffect(() => {
        async function loadStats() {
            //const { data: userData } = await supabase.auth.getUser();
            //const user = userData.user;
            //if (!user) return;
            if (cards.length === 0) return;

            const ids = cards.map((c) => c.id);

            const { data, error } = await supabase
                .from("card_stats")
                .select("card_id, review_count, ease_factor, last_reviewed_at")
                .gt("review_count", 0)
                .in("card_id", ids);

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
    }, [cards]);
    // 计时器：全局顶栏那个
    const { reset, start, pause } = useTimer();
    useEffect(() => {
        reset()
        // 离开页面：暂停计时器
        return () => {
            pause();
        };
        // 我们就是想只在挂载/卸载时触发一次，所以依赖用 []
    },[]);
// ② isBreak 控制计时器运行/暂停
    useEffect(() => {
        if (isBreak) {
            pause();   // 看答案 → 暂停计时
        } else {
            start();   // 做题阶段 → 开始计时
        }
    }, [isBreak, start, pause]);


    // 3. 切题 / 翻面
    const prevCard = () => {
        if (cards.length === 0) return;
        setShowBack(false);
        setIndex((i) => (i - 1 + cards.length) % cards.length);
    };

    const nextCard = () => {
        if (cards.length === 0) return;
        setShowBack(false);
        setIndex((i) => (i + 1) % cards.length);
    };

    const flip = () => setShowBack((v) => !v);

    // 4. 记录掌握程度（写入 card_stats 和 card_reviews，并自动下一题）
    async function recordDifficulty(level: number) {
        // 拍下当前卡片（快照）
        const currentCard = cards[index];
        if (!currentCard) return;

        // UI 立即跳到下一张卡并回到正面
        nextCard();

        // 后台写数据库
        const { data: userData } = await supabase.auth.getUser();
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

        // ------- 1) 记录 card_reviews（一条记录就插入一次） -------
        await supabase.from("card_reviews").insert({
            user_id,
            card_id,
            reviewed_at: now,
            user_answer: null,         // 你目前没有输入作答内容
            is_correct: null,          // 没有对错概念，写 null
            time_spent: null,          // 如果需要计时可以以后加
            meta: { difficulty: ease_factor } // 把点击难度记在 meta 里
        });

        // ------- 2) 更新 card_stats（累积统计） -------
        const { data: existing } = await supabase
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
                correct_count: 0,
                wrong_count: 0,
                ease_factor,
                last_reviewed_at: now
            });
            // 本地也更新一下 map
            setCardStatsMap((prev) => ({
                ...prev,
                [card_id]: {
                    card_id,
                    review_count: 1,
                    ease_factor,
                    last_reviewed_at: now,
                },
            }));
        } else {
            const newReviewCount = (existing.review_count || 0) + 1;
            await supabase
                .from("card_stats")
                .update({
                    review_count: newReviewCount,
                    ease_factor,
                    last_reviewed_at: now
                })
                .eq("id", existing.id);
            setCardStatsMap((prev) => ({
                ...prev,
                [card_id]: {
                    card_id,
                    review_count: newReviewCount,
                    ease_factor,
                    last_reviewed_at: now,
                },
            }));
        }
        setAnswersSinceBreak((prev) => {
            const next = prev + 1;

            if (next >= CARD_THRESHOLD) {
                setIsBreak(true);   // 进入休息模式
            }

            return next;
        });
    }

    // 5. 状态渲染
    // 5. 状态渲染
    if (loading) return <div>正在抽取练习卡片…</div>;
    if (!deckName) return <div className="text-sm text-slate-500">未找到该题库或目录。</div>;
    if (cards.length === 0) return <div className="text-sm text-slate-500">当前目录下暂无可练习的卡片。</div>;

    const current = cards[index];
    const currentStats = cardStatsMap[current.id];
//    const difficultyLevel = currentStats?.ease_factor;
    const reviewCount = currentStats?.review_count ?? 0;
    const completionRatio = (() => {
        if (cards.length === 0) return 0;

        let total = 0;
        for (const c of cards) {
            const stats = cardStatsMap[c.id];
            const level = stats?.ease_factor ?? 0;
            total += level;
        }
        return (total + (folderStats?.total_ease_factor ?? 0) - totalEaseFactorOfCards.current)
            / ((folderStats?.total_items ?? 0) * 4);
    })();
    const completionText = (completionRatio * 100).toFixed(0) + "%";
    const frontClean = trimEmptyLines(current.front);
    const backClean = trimEmptyLines(current.back);
    const { sizeClass: frontSizeClass, alignClass: frontAlign } = getContentSizeClass(frontClean);
    const { sizeClass: backSizeClass, alignClass: backAlign } = getContentSizeClass(backClean);
    const isDarkMode =
        typeof document !== "undefined" &&
        document.documentElement.classList.contains("dark");
    const ringBgColor = isDarkMode ? "#1f2937" : "#e2e8f0";

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
            <div className="mb-4 flex items-center justify-start gap-4">
                {/* 左：标题 */}
                <div>
                    <h1 className="text-xl font-semibold">{deckName}</h1>
                    <div className="text-xs text-slate-500 mt-1">
                        <span>第 {answersSinceBreak} / {cards.length} /{folderStats?.total_items} 张 </span>

                    </div>
                </div>
                {/* 中间：一排圆点，每个表示一张卡片 */}
                <div className="w-[30rem] md:w-[34rem] mt-1 flex flex-wrap items-center justify-center gap-4">
                    <div className="w-4"></div>
                    {cards.map((card, idx) => {
                        const stats = cardStatsMap[card.id];
                        const isCurrent = idx === index;              // 当前卡

                        const difficultyLevel = stats?.ease_factor ?? 0;   // 1~4 或 0 未练过

                        const glowRingColors: Record<number, string> = {
                            1: "ring-purple-400",
                            2: "ring-orange-400",
                            3: "ring-green-400",
                            4: "ring-blue-400",
                        };

                        const colorClass = easeFactorToColor(difficultyLevel) // 未练过 = 灰色
                        const glowClass =
                            difficultyLevel >= 1 && difficultyLevel <= 4
                                ? glowRingColors[difficultyLevel]
                                : "ring-neutral-300"; // 兜底发光颜色

                        return (
                            <div className="w-[24px] flex justify-center">
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
                    <div className="absolute w-10 h-10 rounded-full flex items-center justify-center text-xs bg-white text-slate-800 dark:bg-slate-700 dark:text-slate-50 shadow-sm">
                        {completionText}
                    </div>
                </div>
            </div>

            {/* 主区域：闪卡 */}
            <div className="flex items-center justify-center gap-4 mt-6">
                <Card
                    className={clsx(
                        "w-[38rem] md:w-[42rem]",
                        "group cursor-pointer select-none",
                        "p-0 border border-slate-300 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-900/50 dark:shadow-[0_16px_36px_-14px_rgba(0,0,0,0.7)]"
                    )}
                >
                    {/* ✅ 顶部状态栏：难度 + 练习次数 */}
                    <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-300 mb-0">
                        {/* 难度颜色条 */}
                        <div className="flex-1 mr-3">
                            {current.deck_title}
                        </div>

                        {/* 练习次数 */}
                        <div className="text-xs text-slate-500 dark:text-slate-300 whitespace-nowrap">
                            练习次数：{reviewCount}
                        </div>
                    </div>
                    {/* 3D 翻转容器 */}
                    <div
                        className={clsx(
                            "relative w-full h-full",
                            "min-h-[16rem] md:min-h-[18rem]",
                            "transition-transform duration-500",
                            "[transform-style:preserve-3d]",
                            "[perspective:1000px]"
                        )}
                        style={{
                            transform: showBack ? "rotateY(180deg)" : "rotateY(0deg)",
                        }}
                        onClick={flip}
                    >
                        {/* 正面 */}
                        <div
                            className={clsx(
                                "absolute inset-0",
                                "flex flex-col",
                                "px-8 pt-2 pb-1 md:px-10 md:pt-3 md:pb-1",
                                "rounded-2xl",
                                "bg-transparent text-slate-900 dark:bg-transparent dark:text-slate-100",
                                "[backface-visibility:hidden]"
                            )}
                        >
                            {/* 内容居中 */}
                            <div className={clsx(
                                "flex-1 flex justify-center whitespace-pre-line px-2 max-h-[24rem] overflow-y-auto",
                                frontSizeClass,
                                frontAlign
                            )}>
                                {frontClean}
                            </div>

                            {/* 底部提示：看答案 */}
                            <div className="text-center opacity-0 group-hover:opacity-70 transition-opacity duration-200 pb-0">
  <span className="text-sm text-blue-600 dark:text-blue-300 underline leading-tight pointer-events-none">
    {showBack ? "点击查看题目" : "点击查看答案"}
  </span>
                            </div>
                        </div>

                        {/* 背面 */}
                        <div
                            className={clsx(
                                "absolute inset-0",
                                "flex flex-col",
                                "px-8 pt-2 pb-1 md:px-10 md:pt-3 md:pb-1",
                                "rounded-2xl",
                                "bg-emerald-200 text-slate-900 dark:bg-slate-700 dark:text-slate-100",
                                "[backface-visibility:hidden]",
                                "[transform:rotateY(180deg)]"
                            )}
                        >
                            <div className={clsx(
                                "flex-1 flex justify-center whitespace-pre-line px-2 max-h-[24rem] overflow-y-auto",
                                backSizeClass,
                                backAlign
                            )}>
                                {backClean}
                            </div>

                            {/* 底部链接：看题目 */}
                            <div className="text-center opacity-0 group-hover:opacity-70 transition-opacity duration-200 pb-0">
  <span className="text-sm text-blue-600 dark:text-blue-300 underline leading-tight pointer-events-none">
    {showBack ? "点击查看题目" : "点击查看答案"}
  </span>
                            </div>
                        </div>
                    </div>
                </Card>
            </div>

            {/* 一排四个掌握程度按钮 */}
            {showBack && (
            <div className="flex justify-center gap-3 mt-6 w-full">
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
                    className="bg-green-600 hover:bg-green-700 text-slate-100 px-4 py-2 rounded font-normal"
                >
                    还行吧
                </Button>

                <Button variant="none"
                    onClick={() => recordDifficulty(4)}
                    className="bg-blue-500 hover:bg-blue-600 text-slate-100 px-4 py-2 rounded font-normal"
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
