import {useEffect, useState, useMemo} from "react";
import {useParams, useNavigate} from "react-router-dom";
import {BookOpen, Trophy, Trash2} from "lucide-react";
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
    deck_name: string;
    attempt_count: number;
    last_score: number | null;
};

type UserRunSummary = {
    id: string;
    template_id: string | null;
    started_at: string | null;
    finished_at: string | null;
    score: number | null;
    config: Record<string, unknown> | null;
};

export default function QuizResultPage() {
    const navigate = useNavigate();
    const {quizId, runId} = useParams<{ quizId?: string; runId?: string }>();
    const [result, setResult] = useState<QuizRunRecord | null>(null);
    const [templateStats, setTemplateStats] = useState<TemplateStats | null>();
    const [userRuns, setUserRuns] = useState<UserRunSummary[]>([]);
    const [loading, setLoading] = useState(true);
    const [runsLoading, setRunsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [runMessage, setRunMessage] = useState<string | null>(null);
    const [deleting, setDeleting] = useState(false);

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
                    .select("id, title, description, deck_name, attempt_count, last_score")
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

            const targetTemplateId = quizId ?? (run as any)?.template_id ?? null;
            if (targetTemplateId) {
                setRunsLoading(true);
                const {data: runsData, error: runsErr} = await supabase
                    .from("quiz_runs_user")
                    .select("id, template_id, started_at, finished_at, score, config")
                    .eq("template_id", targetTemplateId)
                    .order("finished_at", {ascending: false});

                if (!runsErr && runsData) {
                    setUserRuns(runsData as UserRunSummary[]);
                }
                setRunsLoading(false);
            }

            setLoading(false);
        }

        void load();
    }, [quizId, runId]);

    const title = templateStats?.title;
    const correct = result?.correct_items ?? 0;
    const total = result?.total_items ?? 0;
    const percent = total > 0 ? Math.round((correct / total) * 100) : 0;
    const hasRun = Boolean(runId && result);
    const hasHistory = userRuns.length > 0;
    const avgScore = useMemo(() => {
        if (!userRuns.length) return null;
        const valid = userRuns.filter((r) => typeof r.score === "number");
        if (!valid.length) return null;
        const sum = valid.reduce((acc, r) => acc + ((r.score ?? 0) as number), 0);
        return sum / valid.length;
    }, [userRuns]);

    async function handleDeleteTemplate() {
        if (!quizId && !templateStats?.id) return;
        const targetId = quizId ?? templateStats?.id;
        if (!targetId) return;
        const ok = window.confirm("确认删除该测验模板？此操作不可恢复。");
        if (!ok) return;
        setDeleting(true);
        const {error: delErr} = await supabase.from("quiz_templates").delete().eq("id", targetId);
        setDeleting(false);
        if (delErr) {
            alert("删除失败，请稍后再试");
            console.error("delete template error", delErr);
            return;
        }
        navigate(`/quizzes?path=${templateStats?.deck_name ?? ""}`);
        //window.location.href = "/quizzes";
    }

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

    return (
        <div className="max-w-3xl mx-auto py-10 px-4 text-slate-900 dark:text-slate-100 space-y-6">
            {/* 标题和描述 */}
            <div className="flex items-center gap-3 mb-4">
                <BookOpen className="w-10 h-10 text-emerald-600 dark:text-emerald-400" />
                <div className="flex-1">
                    <div className="text-xl font-semibold text-slate-900 dark:text-white">
                        {title}
                    </div>
                    <div className="text-xs text-slate-600 dark:text-slate-400 mt-1">
                        {templateStats?.description}
                    </div>
                </div>
                <div className="flex-1 flex justify-end">
                    <Button variant="link"
                            onClick={() => navigate(`/quizzes?path=${templateStats?.deck_name ?? ""}`)}
                        >
                        返回测验列表
                    </Button>
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
                        <div className="flex flex-wrap mt-5 justify-end">

                            {result?.template_id && (
                                <Button variant="primary"
                                        onClick={() => navigate(`/quizzes/${result.template_id}/take`)}
                                >
                                    再做一次
                                </Button>
                            )}
                        </div>
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
                    <div className="space-y-2 text-base">

                        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-700 dark:text-slate-300">
                            <div className="flex flex-wrap items-center gap-3">
                            <span>测验次数：{templateStats.attempt_count ?? 0}</span>
                            {typeof templateStats.last_score === "number" && (
                                <span>最后成绩：{Math.round((templateStats.last_score ?? 0) * 100)}%</span>
                            )}
                            {typeof avgScore === "number" && (
                                <span>平均成绩：{Math.round(avgScore * 100)}%</span>
                            )}
                            </div>
                            <Button
                                variant="ghost"
                                disabled={deleting}
                                onClick={handleDeleteTemplate}
                                className="text-sm px-2 py-2"
                                title="删除测验"
                            >
                                {deleting ? "删除中…" : <Trash2 className="w-4 h-4 text-red-500 dark:text-red-400" />}
                            </Button>
                        </div>
                    </div>
                ) : (
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                        {runMessage ?? "暂无统计信息。"}
                    </div>
                )}
            </div>

            {/* 历史测验记录 */}
            <div
                className="rounded-2xl border border-slate-200 bg-white/80 p-6 text-slate-800 shadow-sm dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200">
                <div className="text-sm font-semibold mb-3 text-slate-900 dark:text-slate-100">历史测验记录</div>
                {runsLoading && (
                    <div className="text-xs text-slate-500 dark:text-slate-400">加载历史记录中…</div>
                )}
                {!runsLoading && hasHistory ? (
                    <div className="space-y-2 text-xs text-slate-700 dark:text-slate-300">
                        {userRuns.map((r) => (
                            <div
                                key={r.id}
                                className="rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900/50"
                            >
                                <div className="flex flex-col">
                                    <span className="font-medium">
                                        得分：{typeof r.score === "number"
                                        ? Math.round((r.score ?? 0) * 100) + "%"
                                        : "-"}
                                    </span>
                                    <span className="text-slate-500 dark:text-slate-400">开始：{r.started_at ?? "-"}</span>
                                    <span className="text-slate-500 dark:text-slate-400">结束：{r.finished_at ?? "-"}</span>
                                </div>
                            </div>
                        ))}
                    </div>
                ) : !runsLoading ? (
                    <div className="text-xs text-slate-500 dark:text-slate-400">暂无历史记录。</div>
                ) : null}
            </div>
        </div>
    );
}
