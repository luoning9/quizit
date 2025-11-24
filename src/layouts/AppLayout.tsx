import { useEffect, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { supabase } from "../../lib/supabaseClient";
import { useTimer } from "../components/TimerContext";

function TimerBar() {
    const { seconds } = useTimer();

    const m = Math.floor(seconds / 60).toString().padStart(2, "0");
    const s = (seconds % 60).toString().padStart(2, "0");

    return (
        <div className="px-3 py-1 text-xs rounded-full bg-slate-800/60 border border-slate-600 text-slate-300 flex items-center gap-1">
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
    //const [isDark, setIsDark] = useState<boolean>(false);

    const navigate = useNavigate();
    const location = useLocation();


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

    return (
        <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-900 dark:text-slate-50">
            {/* 顶部导航 */}
            <header className="border-b border-slate-200 bg-white/80 backdrop-blur dark:bg-slate-900/80 dark:border-slate-700">
                <div className="mx-auto max-w-5xl px-4 py-3 flex items-center justify-between">
                    {/* 左侧 LOGO */}
                    <Link to="/" className="flex items-center gap-2">
                        <div className="h-8 w-8 rounded-xl bg-blue-700 text-white flex items-center justify-center text-sm font-bold shadow-soft dark:bg-brand/80">
                            Q
                        </div>
                        <span className="font-semibold text-lg tracking-tight">
              Quiz Studio
            </span>
                    </Link>

                    {/* 右侧导航 + 用户 + 主题切换 */}
                    <nav className="flex items-center gap-3 text-sm text-slate-600 dark:text-slate-200">
                        <TimerBar />

                        {/* 登录 / 用户信息 */}
                        {user ? (
                            <div className="flex items-center gap-2 text-[11px] text-slate-500 dark:text-slate-300">
                <span className="max-w-[150px] truncate">
                  {user.email ?? ""}
                </span>
                                <button
                                    type="button"
                                    onClick={handleLogout}
                                    className="px-2 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 dark:bg-slate-700 dark:hover:bg-slate-600"
                                >
                                    退出
                                </button>
                            </div>
                        ) : location.pathname !== "/login" ? (
                            <button
                                type="button"
                                onClick={handleLoginClick}
                                className="text-[11px] px-3 py-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-slate-700 dark:hover:bg-slate-600"
                            >
                                登录
                            </button>
                        ) : null}
                    </nav>
                </div>
            </header>

            {/* 页面内容 */}
            <main className="mx-auto max-w-5xl px-4 py-6">
                <Outlet />
            </main>
        </div>
    );
}