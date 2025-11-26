# AI 生成测验题目 Prompt 模板

用于请求 AI 生成可直接导入的测验 JSON（仅返回 JSON）。先填好占位符，直接发送。

```
填写参数（放在开头方便改动）：
- 题目数量：{count_placeholder} 道（少量=5 / 适中=10 / 多些=20；默认 10）
- 难度：{difficulty_placeholder}（易/中/难；默认 中）
- 主题/范围：{topic_placeholder}
- 题型偏好：{type_placeholder}（默认 single_choice；可选 basic / multiple_choice / fill_in_blank）

---

你是一名出题助理，请生成测验题目并返回 JSON（仅 JSON），格式为：
{
  "items": [
    { "front": { "type": "single_choice", "prompt": "<题干>", "options": ["A1","A2","A3","A4"] }, "back": { "answers": [["A"]] }, "score": 1 }
  ]
}

要求：
- 题目数量、难度、主题/范围按上方参数执行。
- 题型需符合前端渲染格式（与 QuizRunPage 一致）：
  - 默认 single_choice：front.prompt + front.options（顺序对应 A/B/C/D…），back.answers 填正确选项代码数组，如 ["A"]。
  - basic：简答，front.prompt 为题干字符串；back.answers 是答案字符串数组（可多条并行）。
  - multiple_choice：多选，front.options 同单选，back.answers 可含多个代码，如 ["A","C"]。
  - fill_in_blank：front.prompt 中用 {{1}}、{{2}} 标注空位，back.answers 按空位顺序给答案数组。
- 语言：中文；题干清晰不重复，答案准确简洁，数据合理。
- 输出规范：仅返回 JSON，不要解释；score 统一为 1，front/back 使用字符串或题型所需结构。
```

### 类型示例（可复制）

**single_choice（默认）**
```json
{
  "items": [
    {
      "front": {
        "type": "single_choice",
        "prompt": "光在真空中的传播速度是多少？",
        "options": ["3.0×10^8 m/s", "3.0×10^6 m/s", "1.5×10^8 m/s", "1.5×10^6 m/s"]
      },
      "back": { "answers": [["A"]] },
      "score": 1
    }
  ]
}
```

**basic（简答）**
```json
{
  "items": [
    {
      "front": { "type": "basic", "prompt": "声音是由什么产生的？" },
      "back": { "answers": [["声音由物体振动产生。"]] },
      "score": 1
    }
  ]
}
```

**multiple_choice（多选）**
```json
{
  "items": [
    {
      "front": {
        "type": "multiple_choice",
        "prompt": "下列哪些措施可以减小噪声？",
        "options": ["在马路边安装隔音墙", "戴上防噪耳塞", "在教室里大声说话", "给机器加装消音罩"]
      },
      "back": { "answers": [["A","B","D"]] },
      "score": 1
    }
  ]
}
```

**fill_in_blank（填空）**
```json
{
  "items": [
    {
      "front": { "type": "fill_in_blank", "prompt": "声音的三要素包括{{1}}、{{2}}和{{3}}。" },
      "back": { "answers": [["音调","响度","音色"]] },
      "score": 1
    }
  ]
}
```
