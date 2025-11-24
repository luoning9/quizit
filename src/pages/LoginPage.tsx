import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { supabase } from "../../lib/supabaseClient";

export function LoginPage() {
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [loading, setLoading] = useState(false);
    const [errorMsg, setErrorMsg] = useState<string | null>(null);

    const navigate = useNavigate();
    const location = useLocation();
    const from = (location.state as any)?.from ?? "/";

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        setLoading(true);
        setErrorMsg(null);

        try {
            const { error } = await supabase.auth.signInWithPassword({
                email,
                password,
            });

            if (error) throw error;

            navigate(from, { replace: true });
        } catch (err: any) {
            setErrorMsg("登录失败，请检查邮箱和密码。");
        } finally {
            setLoading(false);
        }
    }

    return (
        <div className="max-w-md mx-auto mt-10 bg-white rounded-2xl shadow-soft p-6">
            <h1 className="text-xl font-semibold mb-3">登录</h1>
            <p className="text-xs text-slate-500 mb-4">请输入邮箱与密码。</p>

            <form onSubmit={handleSubmit} className="space-y-3">
                <input
                    type="email"
                    required
                    placeholder="邮箱"
                    className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand/40"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                />

                <input
                    type="password"
                    required
                    placeholder="密码"
                    className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand/40"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                />

                {errorMsg && (
                    <div className="text-xs text-red-500 mt-1">{errorMsg}</div>
                )}

                <button
                    type="submit"
                    disabled={loading}
                    className="w-full px-4 py-2 rounded-xl bg-brand text-white text-sm disabled:opacity-60"
                >
                    {loading ? "登录中…" : "登录"}
                </button>
            </form>
        </div>
    );
}