// edge/gen-questions/index.ts
// 根据传入参数调用 OpenAI 生成题目占位示例。
import { serve } from "https://deno.land/std@0.200.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.48.0";

type GenerateRequest = {
  prompt?: string;
  count?: number;
  difficulty?: "easy" | "medium" | "hard";
  questionTypes?: Array<"single" | "multiple" | "fill_in_blank" | "basic">;
  path?: string;
  mode?: string; // 占位
  cards?: Array<{ front: string; back: string }>;
};


const OPENAI_API_KEY = Deno.env.get("OPENAI_API_KEY");
// 不再访问数据库

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, apikey, X-Client-Info, x-client-info",
};

serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 200, headers: corsHeaders });
  }

  if (!OPENAI_API_KEY) {
    return new Response(JSON.stringify({ error: "Missing OPENAI_API_KEY" }), {
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

  let payload: GenerateRequest;
  try {
    payload = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "Invalid JSON" }), {
      status: 400,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  const prompt = (payload.prompt ?? "").trim();
  const count = Math.min(Math.max(Number(payload.count) || 5, 1), 25);
  const difficulty = payload.difficulty ?? "medium";
  const types = (payload.questionTypes?.length ? payload.questionTypes : ["single"]) as string[];
  const selectedCards =
    Array.isArray(payload.cards)
      ? payload.cards
          .map((row) => ({
            front: String(row.front ?? "").trim(),
            back: String(row.back ?? "").trim(),
          }))
          .filter((row) => row.front || row.back)
      : [];

  if (selectedCards.length === 0) {
    return new Response(JSON.stringify({ error: `no cards provided` }), {
      status: 400,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
  const selected_cards = JSON.stringify(selectedCards);

  const systemPrompt =
    "你是一名中学老师的出题助理。请根据考察内容生成题目，并严格按照输出结构生成JSON。" +
      "考察内容一般是一个数组，每个元素有front字段，如果front字段大都是英文，请使用英语出题。";

  const userPrompt = `
在生成题目时尽量满足如下要求：${prompt}

----------------------------
一、任务参数
----------------------------
题目数量：${count}
难度：${difficulty}
题型：${types.join(",")}
考察内容：所出的题目应该考察与下面知识卡片紧密相关的内容
${selected_cards}

----------------------------
二、JSON 输出结构（必须严格遵守）
----------------------------
无论题型，每题结构必须为：

{
"front": { ... },
"back": { ... },
"score": 1
}

front 与 back 必须是并列字段，禁止将 back 嵌套到 front 内部。

score 固定为 1。

----------------------------
三、题型格式规范（必须严格遵守）
----------------------------

1) 单选题 single_choice
   {
   "front": {
   "type": "single_choice",
   "prompt": "题干……",
   "options": ["A1", "A2", "A3", "A4"]
   },
   "back": { "answers": [["A"]] },
   "score": 1
   }

2) 多选题 multiple_choice
   {
   "front": {
   "type": "multiple_choice",
   "prompt": "题干……",
   "options": ["A1", "A2", "A3", "A4"]
   },
   "back": { "answers": [["A"], ["C"]] },
   "score": 1
   }

3) 填空题 fill_in_blank（重点：不能产生嵌套错误）
   {
   "front": {
   "type": "fill_in_blank",
   "prompt": "……{{1}}……{{2}}……"
   },
   "back": {
   "answers": [["空1答案"], ["空2答案"]]
   },
   "score": 1
   }

注意：
- prompt 中的空只能用 {{数字}} 表示。
- back.answers 必须是二维数组。
- back 不得放入 front 内部。

----------------------------
四、图片处理规则（严格执行）
----------------------------
若题干包含图片，使用如下格式且需独立成段：

![图片描述]

多张图片写为：

![图片 1：……]
![图片 2：……]

图片描述要求简短、准确，不使用任何括号符号。

----------------------------
五、输出规范
----------------------------
1. 仅输出 JSON，不附加解释。
2. 所有题目必须符合主题范围与题型要求。
3. 所有题目必须来自我提供的试卷资料（原题或改编）。
4. front 与 back 必须严格保持并列结构。

----------------------------
结束。
`;

  try {
    const aiResp = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${OPENAI_API_KEY}`,
      },
      body: JSON.stringify({
        model: "gpt-5-mini",
        messages: [
          { role: "system", content: systemPrompt },
          { role: "user", content: userPrompt },
        ],
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
    const content = data?.choices?.[0]?.message?.content ?? "";

    // 如果 content 是合法 JSON，直接返回解析后的 JSON；否则返回错误结构
    try {
      const parsed = JSON.parse(content);
      return new Response(JSON.stringify(parsed), {
        status: 200,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      });
    } catch {
      const fallback = {
        error: "not json format",
        content,
        prompt,
        count,
        difficulty,
        questionTypes: types,
      };
      return new Response(JSON.stringify(fallback), {
        status: 200,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      });
    }
  } catch (err) {
    console.error("gen-questions error", err);
    return new Response(JSON.stringify({ error: "Internal error" }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
});
