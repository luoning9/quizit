// edge/check-answer/index.ts
import { serve } from "https://deno.land/std@0.200.0/http/server.ts";

type CheckRequest = {
  standardAnswer?: string;
  userAnswer?: string;
};

type CheckResponse = {
  correct: boolean;
  reason?: string;
};

const OPENAI_API_KEY = Deno.env.get("OPENAI_API_KEY");

serve(async (req) => {
  if (!OPENAI_API_KEY) {
    return new Response(JSON.stringify({ error: "Missing OPENAI_API_KEY" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed" }), {
      status: 405,
      headers: { "Content-Type": "application/json" },
    });
  }

  let payload: CheckRequest;
  try {
    payload = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "Invalid JSON" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const standardAnswer = payload.standardAnswer ?? "";
  const userAnswer = payload.userAnswer ?? "";

  if (!standardAnswer || !userAnswer) {
    return new Response(JSON.stringify({ error: "standardAnswer and userAnswer are required" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const systemPrompt =
    "你是答案判定器。只用 JSON 回复：要么 {\"correct\":true}，要么 {\"correct\":false,\"reason\":\"...\"}。 " +
    "如果答案错误，必须给出简短原因（不超过 40 个词）。忽略大小写和轻微格式差异。不要输出 JSON 外的任何文字。";

  const userPrompt = `Standard answer: ${standardAnswer}\nUser answer: ${userAnswer}\nIs the user answer correct?`;

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
        max_tokens: 80,
      }),
    });

    if (!aiResp.ok) {
      const errText = await aiResp.text();
      console.error("OpenAI error", aiResp.status, errText);
      return new Response(JSON.stringify({ error: "OpenAI request failed" }), {
        status: 502,
        headers: { "Content-Type": "application/json" },
      });
    }

    const data = await aiResp.json();
    const content = data?.choices?.[0]?.message?.content?.trim() ?? "";

    let correct = false;
    let reason = "";
    try {
      const parsed = JSON.parse(content);
      correct = Boolean(parsed.correct);
      reason = typeof parsed.reason === "string" ? parsed.reason : "";
    } catch {
      correct = /true/i.test(content);
    }

    if (!correct && !reason && content && !/true/i.test(content)) {
      // Fallback: use raw content as reason if parsing failed or model omitted it.
      reason = content.slice(0, 200);
    }

    const result: CheckResponse = { correct };
    if (!correct) {
      result.reason = reason || "答案与标准不匹配";
    }

    return new Response(JSON.stringify(result), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    console.error("check-answer error", err);
    return new Response(JSON.stringify({ error: "Internal error" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
});
