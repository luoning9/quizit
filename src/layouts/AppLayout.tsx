import { useEffect, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { supabase } from "../../lib/supabaseClient";
import { useTimer } from "../components/TimerContext";
import { Button } from "../components/ui/Button";
import { Moon, Sun, Sparkles, Bell, BarChart3 } from "lucide-react";

function TimerBar() {
    const { seconds } = useTimer();

    const m = Math.floor(seconds / 60).toString().padStart(2, "0");
    const s = (seconds % 60).toString().padStart(2, "0");

    return (
        <div className="px-3 py-1 text-xs rounded-full bg-white/20 border border-white/30 text-white flex items-center gap-1 dark:bg-slate-800/60 dark:border-slate-600 dark:text-slate-300">
            <span>计时 </span>
            <span className="font-mono inline-block min-w-[3.5rem] text-center">
                {m}:{s}
            </span>
        </div>
    );
}

interface UserInfo {
    email: string | null;
}

export function AppLayout() {
    const [user, setUser] = useState<UserInfo | null>(null);
    const [theme, setTheme] = useState<"light" | "dark">(() => {
        if (typeof window === "undefined") return "dark";
        const saved = localStorage.getItem("theme");
        if (saved === "light" || saved === "dark") return saved;
        return window.matchMedia("(prefers-color-scheme: dark)").matches
            ? "dark"
            : "light";
    });

    const navigate = useNavigate();
    const location = useLocation();
    const [navRecentNewCount, setNavRecentNewCount] = useState<number>(0);
    const [navDueCount, setNavDueCount] = useState<number>(0);


    // 登录状态监听
    useEffect(() => {
        supabase.auth.getUser().then(({ data }) => {
            if (data.user) {
                setUser({ email: data.user.email ?? null });
            }
        });

        const { data: subscription } = supabase.auth.onAuthStateChange(
            (_event, session) => {
                if (session?.user) {
                    setUser({ email: session.user.email ?? null });
                } else {
                    setUser(null);
                }
            }
        );

        return () => {
            subscription.subscription.unsubscribe();
        };
    }, []);

    async function handleLogout() {
        await supabase.auth.signOut();
        navigate("/");
    }

    function handleLoginClick() {
        navigate("/login", { state: { from: location.pathname } });
    }

    // 同步主题到 <html>，并持久化
    useEffect(() => {
        const root = document.documentElement;
        if (theme === "dark") {
            root.classList.add("dark");
        } else {
            root.classList.remove("dark");
        }
        localStorage.setItem("theme", theme);
    }, [theme]);

    function toggleTheme() {
        setTheme((prev) => (prev === "dark" ? "light" : "dark"));
    }

    return (
        <div className="min-h-screen bg-slate-100 text-slate-900 dark:bg-slate-900 dark:text-slate-50">
            {/* 顶部导航 */}
            <header className="border-b border-transparent bg-emerald-700 text-white shadow-md backdrop-blur dark:bg-slate-900/80 dark:border-slate-700 dark:text-slate-100">
                <div className="mx-auto max-w-5xl px-4 py-3 flex items-center justify-between">
                    {/* 左侧 LOGO */}
                    <div className="flex items-center gap-2">
                        <Link to="/" className="flex items-center gap-2">
                            <div className="h-8 w-8 rounded-xl bg-blue-700 text-white flex items-center justify-center text-sm font-bold shadow-soft dark:bg-brand/80">
                                Q
                            </div>
                            <span className="font-semibold text-lg tracking-tight text-white dark:text-slate-50">
              Quiz Studio
            </span>
                        </Link>
                    </div>

                    {/* 右侧导航 + 用户 + 主题切换 */}
                    <nav className="flex items-center gap-3 text-sm text-white dark:text-slate-200">
                        <TimerBar />
                        <Button
                            variant="ghost"
                            className="text-base text-white dark:text-slate-200"
                            onClick={() => navigate("/decks/newest")}
                        >
                            <Sparkles size={14} className="mr-1" />
                            新卡片
                            {navRecentNewCount > 0 && (
                                <span className="ml-1 inline-flex items-center justify-center min-w-[20px] h-[20px] px-1 rounded-full bg-yellow-400 text-slate-900 text-[10px] font-semibold leading-none">
                                    {navRecentNewCount >= 100 ? "99+" : navRecentNewCount}
                                </span>
                            )}
                        </Button>
                        <Button
                            variant="ghost"
                            className="text-base text-white dark:text-slate-200"
                            onClick={() => navigate("/decks/due")}
                        >
                            <Bell size={14} className="mr-1" />
                            待复习
                            {navDueCount > 0 && (
                                <span className="ml-1 inline-flex items-center justify-center min-w-[20px] h-[20px] px-1 rounded-full bg-red-500 text-white text-[10px] font-semibold leading-none">
                                    {navDueCount >= 100 ? "99+" : navDueCount}
                                </span>
                            )}
                        </Button>
                        {/* 登录 / 用户信息 */}
                        {user ? (
                            <div className="flex items-center gap-2 text-[11px] text-white dark:text-slate-300">
                                <span className="max-w-[150px] truncate">
                                    {user.email ?? ""}
                                </span>
                                <Button
                                    variant="ghost"
                                    className="text-base text-white dark:text-slate-200"
                                    onClick={() => navigate("/stats")}
                                    title="学习统计"
                                >
                                    <BarChart3 size={18} />
                                </Button>
                                <Button
                                    type="button"
                                    variant="none"
                                    className="px-3 py-1.5 text-[11px] rounded-lg text-white border border-white/30 hover:bg-white/20"
                                    onClick={handleLogout}
                                >
                                    退出
                                </Button>
                            </div>
                        ) : location.pathname !== "/login" ? (
                            <Button
                                type="button"
                                variant="none"
                                className="text-[11px] px-3 py-1.5 rounded-xl text-white border border-white/30 hover:bg-white/20"
                                onClick={handleLoginClick}
                            >
                                登录
                            </Button>
                        ) : null}

                        <Button
                            type="button"
                            variant="none"
                            className="text-[11px] px-3 py-1.5 rounded-xl text-white border-white/30 hover:bg-white/20"
                            onClick={toggleTheme}
                            aria-label="切换主题"
                            title={`切换为${theme === "dark" ? "浅色" : "深色"}主题`}
                        >
                            {theme === "dark" ? (
                                <Sun size={16} className="text-white drop-shadow-sm" />
                            ) : (
                                <Moon size={16} className="text-white drop-shadow-sm" />
                            )}
                        </Button>
                    </nav>
                </div>
            </header>

            {/* 页面内容 */}
            <main className="mx-auto max-w-5xl px-4 py-6 bg-white/90 dark:bg-slate-900/70 rounded-2xl shadow-sm dark:shadow-[0_10px_30px_-15px_rgba(0,0,0,0.6)]">
                <Outlet context={{ setNavDueCount, setNavRecentNewCount }} />
            </main>
        </div>
    );
}
