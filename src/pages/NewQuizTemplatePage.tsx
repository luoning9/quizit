import React, { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { supabase } from "../../lib/supabaseClient";
import { Button } from "../components/ui/Button";
import clsx from "clsx";

type Mode = "mixed";

interface DraftItem {
  front: string;
  back: string;
  score: number;
}

const SAMPLE_JSON = `{
  "items": [
    { "front": "声音是由什么产生的？", "back": "由物体振动产生。", "score": 1 },
    { "front": "声音在真空中能传播吗？", "back": "不能。", "score": 1 }
  ]
}`;

const PROMPT_TEMPLATE = `你是一名出题助理，请生成测验题目并返回 JSON（仅 JSON），格式为：
{
  "items": [
    { "front": "<题干>", "back": "<答案>", "score": 1 },
    ...
  ]
}

要求：
- 题目数量：{count_placeholder} 道（少量=5 / 适中=10 / 多些=20）
- 难度：{difficulty_placeholder}（易/中/难）
- 题型：基础问答（可用简洁文本），如需多选/单选可在 front 中写清选项，back 写标准答案。
- 语言：中文
- 主题/范围：{topic_placeholder}
- 内容质量：题干清晰，不要重复；答案准确简洁；如涉及数据请合理化。
- 输出规范：仅返回 JSON，不要附带解释；score 统一为 1，front/back 使用字符串。`;

interface AiDialogProps {
  open: boolean;
  prompt: string;
  setPrompt: (v: string) => void;
  count: "5" | "10" | "20";
  setCount: (v: "5" | "10" | "20") => void;
  difficulty: "easy" | "medium" | "hard";
  setDifficulty: (v: "easy" | "medium" | "hard") => void;
  onGenerate: () => void;
  onClose: () => void;
  loading?: boolean;
}

function AiDialog({
  open,
  prompt,
  setPrompt,
  count,
  setCount,
  difficulty,
  setDifficulty,
  onGenerate,
  onClose,
  loading,
}: AiDialogProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md rounded-2xl bg-white p-4 shadow-xl dark:bg-slate-900 dark:border dark:border-slate-700">
        <div className="flex items-center justify-between mb-3">
          <div className="text-base font-semibold text-slate-900 dark:text-slate-100">
            AI 生成
          </div>
          <Button
            type="button"
            variant="ghost"
            className="text-sm"
            onClick={onClose}
            disabled={loading}
          >
            关闭
          </Button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-sm text-slate-700 dark:text-slate-200">
              提示词
            </label>
            <textarea
              className="mt-1 w-full h-20 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 dark:bg-slate-950/70 dark:border-slate-700 dark:text-slate-100 dark:focus:border-sky-500 dark:focus:ring-sky-300/30"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="例如：生成一道关于力和运动的选择题"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-sm text-slate-700 dark:text-slate-200 mb-1">
                题目数量
              </div>
              <div className="flex gap-2">
                {[
                  { label: "少量", value: "5" },
                  { label: "适中", value: "10" },
                  { label: "多些", value: "20" },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    className={clsx(
                      "px-3 py-1.5 rounded-lg text-sm border",
                      count === opt.value
                        ? "bg-emerald-600 text-white border-emerald-600"
                        : "bg-white text-slate-700 border-slate-300 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-200 dark:border-slate-600 dark:hover:bg-slate-700"
                    )}
                    onClick={() => setCount(opt.value as "5" | "10" | "20")}
                    disabled={loading}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="text-sm text-slate-700 dark:text-slate-200 mb-1">
                难度
              </div>
              <div className="flex gap-2">
                {[
                  { label: "易", value: "easy" },
                  { label: "中", value: "medium" },
                  { label: "难", value: "hard" },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    className={clsx(
                      "px-3 py-1.5 rounded-lg text-sm border",
                      difficulty === opt.value
                        ? "bg-emerald-600 text-white border-emerald-600"
                        : "bg-white text-slate-700 border-slate-300 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-200 dark:border-slate-600 dark:hover:bg-slate-700"
                    )}
                    onClick={() => setDifficulty(opt.value as "easy" | "medium" | "hard")}
                    disabled={loading}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="ghost"
              onClick={onClose}
              disabled={loading}
              className="text-sm"
            >
              取消
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={onGenerate}
              disabled={loading}
              className="text-sm"
            >
              {loading ? "生成中…" : "生成"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function parseItems(text: string): DraftItem[] {
  try {
    const parsed = JSON.parse(text);
    const arr: unknown = Array.isArray(parsed?.items) ? parsed.items : parsed;
    if (!Array.isArray(arr)) return [];

    return arr
      .map((it: any) => ({
        front:
          typeof it.front === "string"
            ? it.front
            : it.front
              ? JSON.stringify(it.front)
              : "",
        back:
          typeof it.back === "string"
            ? it.back
            : it.back
              ? JSON.stringify(it.back)
              : "",
        score:
          typeof it.score === "number" && it.score > 0
            ? it.score
            : typeof it.score === "string" && !Number.isNaN(Number(it.score))
              ? Number(it.score) || 1
              : 1,
      }))
      .filter((it) => it.front.trim().length > 0 || it.back.trim().length > 0);
  } catch {
    return [];
  }
}

export default function NewQuizTemplatePage() {
  const [searchParams] = useSearchParams();
  const path = searchParams.get("path") || "";
  const navigate = useNavigate();

  const [title, setTitle] = useState(path ? `${path} 测验` : "");
  const [description, setDescription] = useState("");
  const [mode] = useState<Mode>("mixed");
  const [itemsText, setItemsText] = useState(SAMPLE_JSON);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [aiOpen, setAiOpen] = useState(false);
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiCount, setAiCount] = useState<"5" | "10" | "20">("10");
  const [aiDifficulty, setAiDifficulty] = useState<"easy" | "medium" | "hard">("medium");
  const [aiLoading, setAiLoading] = useState(false);

  const parsedItems = useMemo(() => parseItems(itemsText), [itemsText]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      setError("标题不能为空");
      return;
    }

    const items = parseItems(itemsText);
    if (!items.length) {
      setError("请提供至少一条题目（front/back/score）。");
      return;
    }

    setSaving(true);

    try {
      const {
        data: { user },
        error: userError,
      } = await supabase.auth.getUser();

      if (userError || !user) {
        setError("请先登录。");
        setSaving(false);
        return;
      }

      const insertPayload = items.map((it) => ({
        owner_id: user.id,
        front: it.front,
        back: it.back,
        card_type: "basic" as const,
      }));

      const { data: insertedCards, error: insertError } = await supabase
        .from("cards")
        .insert(insertPayload)
        .select("id, front, back");

      if (insertError || !insertedCards || insertedCards.length === 0) {
        console.error("insert cards error", insertError);
        setError("创建卡片失败。");
        setSaving(false);
        return;
      }

      const itemsForTemplate = insertedCards.map((c, idx) => ({
        card_id: c.id,
        position: idx + 1,
        score: items[idx]?.score ?? 1,
      }));

      const config = {
        source_path: path,
        question_count: itemsForTemplate.length,
        shuffle: true,
        created_from: "manual",
      };

      const { data: tmpl, error: tmplError } = await supabase
        .from("quiz_templates")
        .insert({
          owner_id: user.id,
          title: trimmedTitle,
          description: description.trim() || null,
          deck_name: path || null,
          mode,
          items: { items: itemsForTemplate },
          config,
        })
        .select("id")
        .single();

      if (tmplError || !tmpl) {
        console.error("insert quiz_template error", tmplError);
        setError("创建测验失败。");
        setSaving(false);
        return;
      }

      navigate(`/quizzes/${tmpl.id}/take`);
    } catch (err) {
      console.error(err);
      setError("出现未知错误。");
      setSaving(false);
    }
  }

  function handleAiGenerate() {
    setAiLoading(true);
    // 先用简单占位生成，后续可替换为 Edge Function 调用
    const countNum = Number(aiCount);
    const prompt = aiPrompt.trim() || "请完善题目";
    const generated = Array.from({ length: countNum }).map((_, idx) => ({
      front: `${prompt} (${idx + 1})`,
      back: `答案（${aiDifficulty}）`,
      score: 1,
    }));
    setItemsText(JSON.stringify({ items: generated }, null, 2));
    setAiLoading(false);
    setAiOpen(false);
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-6 text-slate-900 dark:text-slate-100">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">新建测验</h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            输入题目内容（front/back），系统会为每题创建卡片并生成测验模板。
          </p>
        </div>
        <Button
          variant="link"
          className="text-xs px-0 text-emerald-700 hover:text-emerald-800 underline underline-offset-4 dark:text-sky-300 dark:hover:text-sky-200"
          onClick={() => navigate(-1)}
        >
          返回
        </Button>
      </div>

      {error && (
        <div className="text-sm text-rose-600 border border-rose-200 bg-rose-50 rounded-xl px-3 py-2 dark:text-rose-400 dark:border-rose-500/50 dark:bg-rose-950/40">
          {error}
        </div>
      )}

      <form
        onSubmit={handleSubmit}
        className="rounded-2xl border border-slate-200 bg-white/90 p-4 space-y-4 shadow-sm dark:border-slate-700 dark:bg-slate-900/70"
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="block text-sm text-slate-700 dark:text-slate-200">
              标题 <span className="text-rose-500">*</span>
            </label>
            <input
              type="text"
              className="w-full rounded-xl bg-white border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 dark:bg-slate-950/70 dark:border-slate-700 dark:text-slate-100 dark:focus:border-sky-500 dark:focus:ring-sky-300/30"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="例如：七年级生物测验"
            />
          </div>
          <div className="space-y-1.5">
            <label className="block text-sm text-slate-700 dark:text-slate-200">
              模式
            </label>
            <div className="px-3 py-2 rounded-lg text-sm border bg-slate-50 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:border-slate-600">
              混合（固定）
            </div>
          </div>
        </div>

        <div className="space-y-1.5">
          <label className="block text-sm text-slate-700 dark:text-slate-200">
            描述（可选）
          </label>
          <textarea
            className="w-full h-20 rounded-xl bg-white border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 resize-none dark:bg-slate-950/70 dark:border-slate-700 dark:text-slate-100 dark:focus:border-sky-500 dark:focus:ring-sky-300/30"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="简单描述这个测验的目的或范围。"
          />
        </div>

        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold">题目内容（JSON）</div>
          <div className="flex gap-2">
            <Button variant="ghost" type="button" className="text-sm" onClick={() => setItemsText(SAMPLE_JSON)}>
              使用示例
            </Button>
            <Button variant="outline" type="button" className="text-sm" onClick={() => setAiOpen(true)}>
              AI 生成…
            </Button>
          </div>
        </div>

        <textarea
          className="w-full h-60 text-xs font-mono bg-white border border-slate-300 rounded-xl p-3 text-slate-900 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-200 dark:bg-slate-950/80 dark:border-slate-700 dark:text-slate-100"
          value={itemsText}
          onChange={(e) => setItemsText(e.target.value)}
          placeholder={SAMPLE_JSON}
        />

        <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
          <span>已解析题目：{parsedItems.length} 条</span>
          <span>模式：混合</span>
        </div>

        <div className="flex justify-end">
          <Button
            type="submit"
            variant="primary"
            disabled={saving || !title.trim()}
            className="text-sm px-4 py-2"
          >
            {saving ? "创建中…" : "创建测验"}
          </Button>
        </div>
      </form>

      <AiDialog
        open={aiOpen}
        prompt={aiPrompt}
        setPrompt={setAiPrompt}
        count={aiCount}
        setCount={setAiCount}
      difficulty={aiDifficulty}
      setDifficulty={setAiDifficulty}
      onGenerate={handleAiGenerate}
      onClose={() => setAiOpen(false)}
      loading={aiLoading}
    />
  </div>
  );
}
