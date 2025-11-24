import { useState } from "react";
import { supabase } from "../../lib/supabaseClient";
import {useLocation, useNavigate} from "react-router-dom";

export default function LoginPage() {
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [loading, setLoading] = useState(false);
    const [errorMsg, setErrorMsg] = useState("");
    const location = useLocation<{ from?: string }>();
    const navigate = useNavigate();

    async function handleLogin(e: React.FormEvent) {
        e.preventDefault();
        setLoading(true);
        setErrorMsg("");

        try {
            const { error } = await supabase.auth.signInWithPassword({
                email,
                password,
            });

            if (error) {
                console.error(error);
                setErrorMsg(error.message || "登录失败，请检查邮箱和密码。");
                return;
            }

            const target = location.state?.from ?? "/";
            navigate(target, { replace: true });
        } catch (err) {
            console.error(err);
            setErrorMsg("登录失败，请稍后重试。");
        } finally {
            setLoading(false);
        }
    }

    return (
        <div className="min-h-screen w-full bg-slate-900 flex items-center justify-center px-4">
            <div className="w-full max-w-md bg-slate-800 border border-slate-700 rounded-2xl p-8 shadow-xl">
                <h1 className="text-2xl font-semibold text-white text-center mb-6">
                    登录 Quizit
                </h1>

                <form onSubmit={handleLogin} className="flex flex-col gap-4">

                    <div className="flex flex-col gap-1">
                        <label className="text-slate-300 text-sm">邮箱</label>
                        <input
                            type="email"
                            required
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            className="w-full px-3 py-2 rounded-lg bg-slate-700 text-white placeholder-slate-400 outline-none
                         focus:ring-2 focus:ring-sky-500"
                        />
                    </div>

                    <div className="flex flex-col gap-1">
                        <label className="text-slate-300 text-sm">密码</label>
                        <input
                            type="password"
                            required
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            className="w-full px-3 py-2 rounded-lg bg-slate-700 text-white placeholder-slate-400 outline-none
                         focus:ring-2 focus:ring-sky-500"
                        />
                    </div>

                    {errorMsg && (
                        <div className="text-red-400 text-sm text-center">{errorMsg}</div>
                    )}

                    <button
                        type="submit"
                        disabled={loading}
                        className="w-full py-2.5 rounded-lg bg-sky-600 hover:bg-sky-700 text-white font-medium
                       disabled:bg-slate-500 transition"
                    >
                        {loading ? "登录中..." : "登录"}
                    </button>
                </form>
            </div>
        </div>
    );
}