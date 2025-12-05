# AI 生成测验题目 Prompt 模板

你是一名出题助理，请从我提供的试卷资料中，查找符合主题范围要求的测验题目并返回 JSON（仅 JSON）。

参数如下：
- 题目数量：15 道（少量=5 / 适中=10 / 多些=20；默认 10）
- 难度：中（易/中/难；默认 中）
- 主题/范围：第四单元新民主主义革命兴起
- 题型偏好：single_choice/multiple_choice（默认 single_choice；可选 basic / multiple_choice / fill_in_blank）

---

JSON格式为：
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
- 优先选择有图的题目

图片处理规则（严格执行）：
如果题干中涉及图片，请务必将图片替换为如下格式：

![图片描述]

图片描述要求：
1. 每张图片必须单独写一段，不能合并。
2. 图片描述必须准确、简洁，能明确说明图中内容。
3. 图片描述不得使用任何括号，只能采用如下格式：
   ![…]
4. 若需要区分多张图片，可写成：
   ![图片 1：……]
   ![图片 2：……]

材料题：
如果题目涉及材料，请在题干中包含材料的完整文字，材料中的图片按照上述图片处理规则执行。

### 类型示例（可复制）

**single_choice（默认）**
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

**basic（简答）**
{
  "items": [
    {
      "front": { "type": "basic", "prompt": "声音是由什么产生的？" },
      "back": { "answers": [["声音由物体振动产生。"]] },
      "score": 1
    }
  ]
}

**multiple_choice（多选）**
{
  "items": [
    {
      "front": {
        "type": "multiple_choice",
        "prompt": "下列哪些措施可以减小噪声？",
        "options": ["在马路边安装隔音墙", "戴上防噪耳塞", "在教室里大声说话", "给机器加装消音罩"]
      },
      "back": { "answers": [["A"],["B"],["D"]] },
      "score": 1
    }
  ]
}

**fill_in_blank（填空）**
{
  "items": [
    {
      "front": { "type": "fill_in_blank", "prompt": "声音的三要素包括{{1}}、{{2}}和{{3}}。" },
      "back": { "answers": [["音调"],["响度"],["音色"]] },
      "score": 1
    }
  ]
}
