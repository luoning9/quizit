import { useNavigate } from "react-router-dom";
import { Button } from "../components/ui/Button";

export function HomePage() {
    const navigate = useNavigate();

    return (
        <div className="space-y-8">

            {/* 1. 大标题区 */}
            <div className="text-center space-y-2">
                <h1 className="text-3xl font-semibold tracking-tight">
                    Knowledge Studio
                </h1>
                <p className="text-slate-600 dark:text-slate-300">
                    Elsa · Jason · 知识记忆背诵
                </p>
            </div>

            {/* 2. 主要功能入口 */}
            <div className="flex justify-center mt-8">
                <div className="flex flex-col md:flex-row gap-6">

                    {/* 闪卡练习 */}
                    <Button
                        variant="primary"
                        className="
    px-12 py-10 text-2xl rounded-2xl shadow-soft
    bg-slate-900 text-slate-50
    hover:bg-slate-700 hover:text-white
    transition-colors

    dark:bg-slate-700 dark:text-slate-100
    dark:hover:bg-slate-600
"
                        onClick={() => navigate("/decks")}
                    >
                        闪卡练习
                    </Button>

                    {/* 去做测验 */}
                    <Button
                        variant="primary"
                        className="
    px-12 py-10 text-2xl rounded-2xl shadow-soft
    bg-slate-900 text-slate-50
    hover:bg-slate-700 hover:text-white
    transition-colors

    dark:bg-slate-700 dark:text-slate-100
    dark:hover:bg-slate-600
"
                        onClick={() => navigate("/quizzes")}
                    >
                        去做测验
                    </Button>
                </div>
            </div>

        </div>
    );
}