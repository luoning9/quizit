import { useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { BookOpen, Trophy } from "lucide-react";
import { supabase } from "../../lib/supabaseClient";
import { Button } from "../components/ui/Button";

type QuizRunRecord = {
  id: string;
  template_id: string | null;
  score: number | null;
  total_items: number | null;
  correct_items: number | null;
  started_at: string | null;
  finished_at: string | null;
  template?: {
    id: string;
    title: string;
    description: string | null;
  } | null;
};

export default function QuizResultPage() {
  const { quizId, runId } = useParams<{ quizId?: string; runId?: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<QuizRunRecord | null>(null);
  const [template, setTemplate] = useState<{ id: string; title: string; description: string | null } | null>(null);
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
            .from("quiz_templates")
            .select("id, title, description")
            .eq("id", quizId)
            .maybeSingle()
        : Promise.resolve({ data: null, error: null });

      const runPromise = runId
        ? supabase
            .from("quiz_runs")
            .select("id, template_id, score, total_items, correct_items, started_at, finished_at, template:quiz_templates(id, title, description)")
            .eq("id", runId)
            .maybeSingle()
        : Promise.resolve({ data: null, error: null });

      const [{ data: tmpl, error: tmplErr }, { data: run, error: runErr }] = await Promise.all([
        templatePromise,
        runPromise,
      ]);

      if ((quizId && (tmplErr || !tmpl))) {
        setError("未找到对应的测验模板。");
        setLoading(false);
        return;
      }

      if (tmpl) {
        setTemplate(tmpl as { id: string; title: string; description: string | null });
      }

      if (runErr) {
        console.error("加载测验结果失败", runErr);
      }

      if (run) {
        setData({
          ...run,
          template: Array.isArray((run as any).template)
            ? (run as any).template[0]
            : (run as any).template ?? null,
        } as QuizRunRecord);
      } else if (runId) {
        setRunMessage("未找到对应的测验记录。");
        setData(null);
      } else {
        setData(null);
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

  const title = template?.title ?? data?.template?.title ?? "测验结果";
  const correct = data?.correct_items ?? 0;
  const total = data?.total_items ?? 0;
  const percent = total > 0 ? Math.round((correct / total) * 100) : 0;
  const hasRun = Boolean(runId && data);

  return (
    <div className="max-w-3xl mx-auto py-10 px-4 text-slate-900 dark:text-slate-100 space-y-6">


      {/* 上半：本次测验结果（可为空或报错） */}
      {hasRun && (
        <div className="rounded-2xl border border-slate-200 bg-white p-6 text-slate-900 shadow-sm dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-100">
            <div className="flex items-center gap-3 mb-4">
                <div>
                    <div className="text-xl font-semibold text-slate-900 dark:text-white">
                        {title}
                    </div>
                    <div className="text-xs text-slate-600 dark:text-slate-400 mt-1">
                        测验完成
                    </div>
                </div>
            </div>
            <div className="flex items-start gap-3">
            <div className="w-12 h-12 rounded-xl bg-emerald-100 text-emerald-700 flex items-center justify-center text-xl font-semibold dark:bg-emerald-900/40 dark:text-emerald-200">
              <Trophy className="w-6 h-6" />
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
                {data?.started_at && <span className="mr-4">开始：{data.started_at}</span>}
                {data?.finished_at && <span>结束：{data.finished_at}</span>}
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
            {data?.template_id && (
              <Link
                to={`/quizzes/${data.template_id}/take`}
                className="px-5 py-2.5 rounded-2xl border border-emerald-500 bg-emerald-50 text-emerald-700 text-sm hover:bg-emerald-100 dark:border-sky-500 dark:bg-sky-900/40 dark:text-sky-200 inline-flex items-center justify-center"
              >
                再做一次
              </Link>
            )}
          </div>
        </div>
      ) }


      {/* 下半：模板统计占位 */}
      <div className="rounded-2xl border border-dashed border-slate-300 bg-white/60 p-6 text-slate-700 shadow-sm dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-300">
        <div className="text-sm font-semibold mb-2 text-slate-800 dark:text-slate-200">
          模板统计（即将呈现）
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400">
          预留区域：将来可展示此测验模板的累计数据和趋势。
        </div>
      </div>
    </div>
  );
}
