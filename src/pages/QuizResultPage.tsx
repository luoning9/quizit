import {useEffect, useState} from "react";
import {useParams, Link} from "react-router-dom";
import {BookOpen, Trophy} from "lucide-react";
import {supabase} from "../../lib/supabaseClient";
import {Button} from "../components/ui/Button";

type QuizRunRecord = {
    id: string;
    template_id: string | null;
    score: number | null;
    total_items: number | null;
    correct_items: number | null;
    started_at: string | null;
    finished_at: string | null;
};

type TemplateStats = {
    id: string;
    title: string;
    description: string | null;
    attempt_count: number;
    last_score: number | null;
};

export default function QuizResultPage() {
    const {quizId, runId} = useParams<{ quizId?: string; runId?: string }>();
    const [result, setResult] = useState<QuizRunRecord | null>(null);
    const [templateStats, setTemplateStats] = useState<TemplateStats | null>();
    //const [stats, setStats] = useState<TemplateStats | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [runMessage, setRunMessage] = useState<string | null>(null);

    useEffect(() => {
        async function load() {
            if (!quizId && !runId) {
                setError("缺少必要参数：需要提供测验模板 ID。");
                setLoading(false);
                return;
            }
            setLoading(true);
            setError(null);
            setRunMessage(null);

            const templatePromise = quizId
                ? supabase
                    .from("quiz_template_stats")
                    .select("id, title, description, attempt_count, last_score")
                    .eq("id", quizId)
                    .maybeSingle()
                : Promise.resolve({data: null, error: null});

            const runPromise = runId
                ? supabase
                    .from("quiz_runs")
                    .select("id, template_id, score, total_items, correct_items, started_at, finished_at, template:quiz_templates(id, title, description)")
                    .eq("id", runId)
                    .maybeSingle()
                : Promise.resolve({data: null, error: null});

            const [{data: tmpl, error: tmplErr}, {data: run, error: runErr}] = await Promise.all([
                templatePromise,
                runPromise,
            ]);

            if ((quizId && (tmplErr || !tmpl))) {
                setError("未找到对应的测验模板。");
                setLoading(false);
                return;
            }

            if (runErr) {
                console.error("加载测验结果失败", runErr);
            }
            if (tmpl) {
                setTemplateStats(tmpl as TemplateStats);
            }
            if (run) {
                setResult({
                    ...run,
                } as QuizRunRecord);
            } else if (runId) {
                setRunMessage("未找到对应的测验记录。");
                setResult(null);
            } else {
                setResult(null);
            }

            setLoading(false);
        }

        void load();
    }, [quizId, runId]);

    if (loading) {
        return (
            <div className="flex flex-col items-center justify-center py-12 text-slate-700 dark:text-slate-300">
                正在加载测验结果…
            </div>
        );
    }

    if (error) {
        return (
            <div
                className="flex flex-col items-center justify-center gap-4 py-12 px-4 text-slate-700 dark:text-slate-300">
                <div className="text-sm">{error}</div>
                <Button variant="outline" onClick={() => (window.location.href = "/quizzes")}>
                    返回测验列表
                </Button>
            </div>
        );
    }

    const title = templateStats?.title;
    const correct = result?.correct_items ?? 0;
    const total = result?.total_items ?? 0;
    const percent = total > 0 ? Math.round((correct / total) * 100) : 0;
    const hasRun = Boolean(runId && result);

    return (
        <div className="max-w-3xl mx-auto py-10 px-4 text-slate-900 dark:text-slate-100 space-y-6">
            <div className="flex items-center gap-3 mb-4">
                <BookOpen className="w-10 h-10 text-emerald-600 dark:text-emerald-400" />
                <div>
                    <div className="text-xl font-semibold text-slate-900 dark:text-white">
                        {title}
                    </div>
                    <div className="text-xs text-slate-600 dark:text-slate-400 mt-1">
                        {templateStats?.description}
                    </div>
                </div>
            </div>

            {/* 上半：本次测验结果（可为空或报错） */}
            {hasRun && (
                <div
                    className="rounded-2xl border border-slate-200 bg-white p-6 text-slate-900 shadow-sm dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-100">

                    <div className="flex items-start gap-3">
                        <div
                            className="w-12 h-12 rounded-xl bg-emerald-100 text-emerald-700 flex items-center justify-center text-xl font-semibold dark:bg-emerald-900/40 dark:text-emerald-200">
                            <Trophy className="w-6 h-6"/>
                        </div>
                        <div className="flex-1 space-y-3">
                            <div className="text-lg">
                                正确题数：
                                <span className="font-semibold text-emerald-700 dark:text-emerald-400">
                  {correct}
                </span>
                                <span className="text-slate-600 dark:text-slate-400"> / {total}</span>
                            </div>
                            <div className="text-sm text-slate-700 dark:text-slate-300">
                                正确率{" "}
                                <span className="font-semibold text-emerald-700 dark:text-sky-400">
                  {percent}%
                </span>
                            </div>
                            <div className="text-xs text-slate-500 dark:text-slate-400">
                                {result?.started_at && <span className="mr-4">开始：{result.started_at}</span>}
                                {result?.finished_at && <span>结束：{result.finished_at}</span>}
                            </div>
                        </div>
                    </div>

                    <div className="flex flex-wrap gap-3 mt-5">
                        <Link
                            to="/quizzes"
                            className="px-5 py-2.5 rounded-2xl border border-slate-300 text-slate-800 text-sm hover:bg-slate-50 dark:border-slate-500 dark:text-slate-200 dark:hover:bg-slate-800 inline-flex items-center justify-center"
                        >
                            返回测验列表
                        </Link>
                        {result?.template_id && (
                            <Link
                                to={`/quizzes/${result.template_id}/take`}
                                className="px-5 py-2.5 rounded-2xl border border-emerald-500 bg-emerald-50 text-emerald-700 text-sm hover:bg-emerald-100 dark:border-sky-500 dark:bg-sky-900/40 dark:text-sky-200 inline-flex items-center justify-center"
                            >
                                再做一次
                            </Link>
                        )}
                    </div>
                </div>
            )}

            {!hasRun && runMessage && (
                <div
                    className="rounded-2xl border border-dashed border-slate-300 bg-white/70 p-4 text-xs text-slate-600 shadow-sm dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-300">
                    {runMessage}
                </div>
            )}

            {/* 下半：模板统计 */}
            <div
                className="rounded-2xl border border-slate-200 bg-white/70 p-6 text-slate-800 shadow-sm dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200">

                {templateStats ? (
                    <div className="space-y-2 text-sm">


                        <div className="text-xs text-slate-600 dark:text-slate-400">
                            测验次数：{templateStats.attempt_count ?? 0}
                            {typeof templateStats.last_score === "number" && (
                                <span
                                    className="ml-4">最后成绩：{Math.round((templateStats.last_score ?? 0) * 100)}%</span>
                            )}
                        </div>
                    </div>
                ) : (
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                        {runMessage ?? "暂无统计信息。"}
                    </div>
                )}
            </div>
        </div>
    );
}
