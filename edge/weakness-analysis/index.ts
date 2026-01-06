import { serve } from "https://deno.land/std@0.200.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.48.0";

type QuestionItem = {
  card_id: string;
  question: string;
  correct_answer: string;
  user_answer: string | null;
};

type AnalyzeRequest = {
  questions?: QuestionItem[];
  deck_ids?: string[];
};

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, apikey, X-Client-Info, x-client-info",
};

const OPENAI_API_KEY = Deno.env.get("OPENAI_API_KEY");
const SUPABASE_URL = Deno.env.get("SUPABASE_URL");
const SUPABASE_ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY");

serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, {
      status: 200,
      headers: corsHeaders,
    });
  }

  if (!OPENAI_API_KEY) {
    return new Response(JSON.stringify({ error: "Missing OPENAI_API_KEY" }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
    return new Response(JSON.stringify({ error: "Missing Supabase configuration" }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed" }), {
      status: 405,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  let payload: AnalyzeRequest;
  try {
    payload = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "Invalid JSON" }), {
      status: 400,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  const questions = Array.isArray(payload.questions) ? payload.questions : [];
  const deckIds = Array.isArray(payload.deck_ids) ? payload.deck_ids : [];
  const deckId = deckIds[0] ?? "";

  if (!questions.length || !deckId) {
    return new Response(JSON.stringify({ error: "questions and deck_ids are required" }), {
      status: 400,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  const authHeader = req.headers.get("Authorization") ?? "";
  const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    global: {
      headers: {
        Authorization: authHeader,
      },
    },
  });

  const { data: deckData, error: deckError } = await supabase
    .from("decks")
    .select("items")
    .eq("id", deckId)
    .maybeSingle();

  if (deckError) {
    console.error("load deck error", deckError);
    return new Response(JSON.stringify({ error: "Failed to load deck" }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  const deckItems =
    (deckData as { items?: { items?: Array<{ card_id?: string }> } } | null)?.items?.items ?? [];
  const cardIds = Array.from(
    new Set(
      deckItems
        .map((item) => item?.card_id)
        .filter((id): id is string => Boolean(id))
    )
  );

  if (!cardIds.length) {
    return new Response(JSON.stringify({ error: "No cards found for deck" }), {
      status: 400,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  const { data: cardsData, error: cardsError } = await supabase
    .from("cards")
    .select("id, front, back")
    .in("id", cardIds);

  if (cardsError) {
    console.error("load cards error", cardsError);
    return new Response(JSON.stringify({ error: "Failed to load cards" }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  const cards = (cardsData ?? []) as Array<{ id: string; front: string; back: string }>;

  const systemPrompt =
    "你是一名熟悉中学课程体系与考试评价方式的教学与知识诊断助理。\n\n" +
    "我将提供两部分数据：\n" +
    "1）测验题目列表（包含 card_id、题目、正确答案、user_answer）\n" +
    "2）该测验对应的知识点闪卡列表（每张闪卡包含 id、front、back）\n\n" +
    "注意：user_answer 可能是错误的，也可能是正确的。\n\n" +
    "你的任务是对**每一道题目进行知识层面的分析**：\n" +
    "- 当 user_answer 错误时：分析学生在“哪些具体知识点（闪卡）”上的理解或运用出现问题；\n" +
    "- 当 user_answer 正确时：分析该题目**主要考察的知识点与能力要求**，指出题目在知识体系中的定位。\n\n" +
    "无论对错，都必须给出“题目—知识点”的对应分析，而不是只做对错判断。\n\n" +
    "分析要求：\n" +
    "- 不要使用“粗心”“运气好”“记错了”等非知识性表述\n" +
    "- 错题分析时，需明确指出：\n" +
    "  - 对应闪卡中的哪一类内容（定义 / 关系 / 计算 / 实验 / 现象 / 方法 / 规则 等）\n" +
    "  - 是概念理解、关系判断、条件辨析、变化趋势、计算运用或情境迁移等哪一层面存在问题\n" +
    "- 对题分析时，需明确指出：\n" +
    "  - 该题主要考察的知识类型与能力层级\n" +
    "  - 在闪卡中对应的关键结论、规则或方法\n" +
    "- 表述要求学术准确、教学视角明确、简洁但信息密度高\n\n" +
    "输出要求（必须严格遵守）：\n" +
    "- 只输出 JSON，不要附加任何解释性文字\n" +
    "- 输出为 JSON 数组\n" +
    "- 字段名、层级结构不得擅自更改\n\n" +
    "输出格式如下：\n\n" +
    "[\n" +
    "  {\n" +
    "    \"card_id\": \"题目对应的 card_id\",\n" +
    "    \"analysis\": \"题目分析说明：若答错，说明对相关闪卡中哪些具体内容理解或运用出现问题；若答对，说明该题主要考察了哪些知识点、规则或能力要求\",\n" +
    "    \"related_cards\": [\n" +
    "      {\n" +
    "        \"id\": \"相关闪卡的 id\",\n" +
    "        \"title\": \"闪卡 front 中的标题\"\n" +
    "      }\n" +
    "    ]\n" +
    "  }\n" +
    "]\n\n" +
    "analysis 字段要求：\n" +
    "- 必须直接指向 related_cards 中闪卡的具体内容\n" +
    "- 字数控制在 90 字以内，说清楚就够了不要啰嗦\n" +
    "- 文字合理分段，例如错因分析单独成段\n" +
    "- 答错时侧重“理解或运用偏差”\n" +
    "- 答对时侧重“考察点与知识覆盖范围”\n" +
    "- 表述自然易懂，不要出现 id 号等系统内部信息\n" +
    "- 不允许出现空泛结论\n\n" +
    "related_cards 要求：\n" +
    "- 只列出与出错原因或题目最相关的 0-2 张闪卡\n" +
    "- 必须有明确对应关系\n\n" +
    "当我提供新的题目数据和闪卡数据时，请直接按照上述要求完成分析并输出 JSON。";

  const userPrompt = JSON.stringify({
    questions,
    cards,
  });

  try {
    const aiResp = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${OPENAI_API_KEY}`,
      },
      body: JSON.stringify({
        model: "gpt-5.1",
        messages: [
          { role: "system", content: systemPrompt },
          { role: "user", content: userPrompt },
        ],
        temperature: 0.2,
      }),
    });

    if (!aiResp.ok) {
      const errText = await aiResp.text();
      console.error("OpenAI error", aiResp.status, errText);
      return new Response(JSON.stringify({ error: "OpenAI request failed" }), {
        status: 502,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      });
    }

    const data = await aiResp.json();
    const content = data?.choices?.[0]?.message?.content?.trim() ?? "";

    let parsed: unknown;
    try {
      parsed = JSON.parse(content);
    } catch {
      return new Response(JSON.stringify({ error: "Invalid AI response" }), {
        status: 502,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      });
    }

    if (!Array.isArray(parsed)) {
      return new Response(JSON.stringify({ error: "AI response is not an array" }), {
        status: 502,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      });
    }

    return new Response(JSON.stringify(parsed), {
      status: 200,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  } catch (err) {
    console.error("weakness-analysis error", err);
    return new Response(JSON.stringify({ error: "Internal error" }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
});
