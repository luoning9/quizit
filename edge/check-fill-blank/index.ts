// edge/check-fill-blank/index.ts
import { serve } from "https://deno.land/std@0.200.0/http/server.ts";

type CheckRequest = {
  prompt?: string;
  standardAnswers?: string[];
  userAnswers?: string[];
};

type CheckDetail = {
  index: number;
  correct: boolean;
  reason?: string;
};

type CheckResponse = {
  correct: boolean;
  reason?: string;
  details?: CheckDetail[];
  userSentence?: string;
  standardSentence?: string;
};

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, apikey, X-Client-Info, x-client-info",
};

const OPENAI_API_KEY = Deno.env.get("OPENAI_API_KEY");

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

  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed" }), {
      status: 405,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  let payload: CheckRequest;
  try {
    payload = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "Invalid JSON" }), {
      status: 400,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  const prompt = payload.prompt ?? "";
  const standardAnswers = payload.standardAnswers ?? [];
  const userAnswers = payload.userAnswers ?? [];

  if (!Array.isArray(standardAnswers) || !Array.isArray(userAnswers)) {
    return new Response(JSON.stringify({ error: "standardAnswers and userAnswers are required" }), {
      status: 400,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  if (!prompt || standardAnswers.length === 0 || userAnswers.length === 0) {
    return new Response(JSON.stringify({ error: "prompt, standardAnswers and userAnswers are required" }), {
      status: 400,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  if (standardAnswers.length !== userAnswers.length) {
    const result: CheckResponse = {
      correct: false,
      reason: "填空数量不匹配",
    };
    return new Response(JSON.stringify(result), {
      status: 200,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }

  const systemPrompt =
    "你是一个考试自动判题系统。\n\n" +
    "任务：\n" +
    "判断“用户答案”是否可以被判为正确。\n\n" +
    "判题原则（学科无关）：\n" +
    "1. 判断标准基于“是否表达了与标准答案相同的核心事实或概念”。\n" +
    "2. 允许合理的语言简化、同义替换、常见省略和表述差异。\n" +
    "3. 不要求用词、句式与标准答案完全一致。\n" +
    "4. 若考生答案未引入错误概念、未改变原有含义、未产生实质性歧义，则可判为正确。\n" +
    "5. 只有在核心含义发生改变、关键条件缺失或引入错误理解时，才判为错误。\n\n" +
    "不需要输出或描述中间推理过程。\n" +
    "只用 JSON 回复：要么 {\"correct\":true}，" +
    "要么 {\"correct\":false,\"reason\":\"...\",\"details\":[...],\"userSentence\":\"...\",\"standardSentence\":\"...\"}。\n" +
    "忽略大小写和轻微格式差异。details 中每一项格式为 " +
    "{\"index\":1,\"correct\":false,\"reason\":\"...\"}。reason 不超过 40 个词。不要输出 JSON 外的任何文字。";

  const userPrompt = JSON.stringify({
    prompt,
    standardAnswers,
    userAnswers,
  });

  try {
    const aiResp = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${OPENAI_API_KEY}`,
      },
      body: JSON.stringify({
        model: "gpt-4o-mini",
        messages: [
          { role: "system", content: systemPrompt },
          { role: "user", content: userPrompt },
        ],
        temperature: 0,
        max_tokens: 120,
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

    let correct = false;
    let reason = "";
    let details: CheckDetail[] | undefined;
    let userSentence = "";
    let standardSentence = "";
    try {
      const parsed = JSON.parse(content);
      correct = Boolean(parsed.correct);
      reason = typeof parsed.reason === "string" ? parsed.reason : "";
      userSentence = typeof parsed.userSentence === "string" ? parsed.userSentence : "";
      standardSentence = typeof parsed.standardSentence === "string" ? parsed.standardSentence : "";
      if (Array.isArray(parsed.details)) {
        details = parsed.details
          .map((item: CheckDetail) => ({
            index: Number(item.index),
            correct: Boolean(item.correct),
            reason: typeof item.reason === "string" ? item.reason : undefined,
          }))
          .filter((item) => Number.isFinite(item.index));
      }
    } catch {
      correct = /true/i.test(content);
    }

    if (!correct && !reason && content && !/true/i.test(content)) {
      reason = content.slice(0, 200);
    }

    const result: CheckResponse = { correct };
    if (!correct) {
      result.reason = reason || "答案与标准不匹配";
      if (details?.length) result.details = details;
      if (userSentence) result.userSentence = userSentence;
      if (standardSentence) result.standardSentence = standardSentence;
    }

    return new Response(JSON.stringify(result), {
      status: 200,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  } catch (err) {
    console.error("check-fill-blank error", err);
    return new Response(JSON.stringify({ error: "Internal error" }), {
      status: 500,
      headers: { "Content-Type": "application/json", ...corsHeaders },
    });
  }
});
