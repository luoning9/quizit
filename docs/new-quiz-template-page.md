# 新建测验页面需求与设计草案

记录“生成新的测验模板”页面的目标、流程与数据契约，供设计/开发/验证参考（可直接据此开发）。

## 1) 背景与目标
- 提供可视化界面，写入一条 `quiz_templates` 记录，快速生成可运行的测验。
- 目标用户：老师/出卷人（需要登录）。
- 成果：成功创建后，可从 `/quizzes/:id/take` 直接开考，并在目录页显示。

## 2) 入口与路由
- 路由：`/quizzes/new`
  - 支持 query：`path`，用于标题前缀和来源标记；缺省为空字符串。
- 入口按钮：目录页（MainSelect）右侧测验列表底部的 “New Quiz”。

## 3) 数据写入与契约
- 写入表：`quiz_templates`
  - 字段：`title`(必填)、`description`(可选)、`related_deck_id`(本场景留空)、`mode`、`items` JSON、`config` JSON、`owner_id`(当前用户)。
- `items` 结构（最终写入模板时，与 `QuizRunPage` 读取兼容）：`{ items: [{ card_id, position, score }] }`
  - `card_id` 由页面在提交时批量创建卡片后获得（完全由输入的 front/back 生成，不依赖 deck）。
  - `position` 从 1 递增；`score` 默认为 1，可在表单内编辑。
- `mode`：支持 `"ordered"`（默认）和 `"mixed"`；如不需要模式切换可固定 `"ordered"`。
- `config` 建议字段：
  - `source_path`
  - `question_count`（实际选题数）
  - `shuffle`: boolean
  - `seed`: string（可选，复现同一试卷）
  - `created_from`: `"manual"` 固定标识

## 4) 页面区域与交互（可视化/可开发）
1) **上下文读取**
   - 从 URL 获取 `path`，用于默认标题前缀和写入 `config.source_path`。无 path 时允许空前缀。
2) **基础信息表单**
   - 标题：默认 `{path} 测验`（path 为空则空字符串），必填，失焦/提交时去掉首尾空格。
   - 描述：多行输入，可空。
   - 模式：固定 `"ordered"`；
3) **题目输入（TextArea，含卡片内容）**
   - TextArea 内容是 JSON，对每题直接写入卡片内容而非 card_id，提交时由系统创建/获取 card 记录并回填 id。
   - 示例（front/back 结构符合 `quizFormat.ts`，最简单可用纯文本）：
     ```json
     {
       "items": [
         { "front": "声音是由什么产生的？", "back": "声音是由物体振动产生的。", "score": 1 },
         { "front": { "type": "single_choice", "prompt": "声音在什么环境中不能传播？", "options": ["空气中","水中","固体中","真空中"], "correct_index": 3 }, "back": "在真空中不能传播。", "score": 2 }
     ]
   }
   ```
   - TextArea 变化时不做实时解析；点击“解析”或提交时 `JSON.parse` 并校验字段与必填项。
   - 按钮：“AI 生成”→ 弹窗输入生成参数，调用 Supabase Edge Function 后返回符合上面 JSON 结构的 items 并写入 TextArea：
     - 参数：`prompt`(必填，文本域)、`count`(单选：少量=5 / 适中=10 / 多些=20，默认 10)、`difficulty`(单选：易/中/难)、`path`(自动带入)、`mode`(单选：ordered/mixed)。
     - 弹窗内显示 loading/错误提示；生成后替换 TextArea 内容，并可手动编辑。
4) **校验规则**
   - 标题必填、长度 > 0。
   - `items.items` 为数组，至少 1 条；每条需包含：
     - `front`：字符串或符合 `quizFormat.ts` 的 JSON；空字符串视为无效。
     - `back`：字符串或 JSON，可空但需存在键。
     - `score`：>0 数字（默认 1）；缺省时补 1。
   - `position` 在解析后按列表顺序重排为 1..n。
5) **提交与反馈（含 cards 创建）**
   - 解析通过后，批量生成 cards 插入 payload：`[{ owner_id, front, back, card_type: "basic" | 推断 }, ...]`。若 front/back 为 JSON，存原文字符串，card_type 取 `basic`。
   - 调用 Supabase `insert` 到 `cards`，获取返回的 `id` 列表。
   - 用返回的顺序组装模板 `items`：`[{ card_id, position, score }]`。
   - 插入 `quiz_templates`，附带 `mode`、`config`（含 `source_path`；`related_deck_id` 为空）。
   - 成功：toast “已创建测验”，跳转 `/quizzes/{id}/take`。
   - 失败：显示错误条（保留用户输入），可重试。
6) **安全/鉴权**
   - 页面挂载时检查登录；未登录则弹提示并引导 `/login`，回调回当前页。

## 6) 非功能要求
- 复用现有 Button/Card/Form 视觉风格（暗色主题），保证移动端可用。
- 文案与错误提示使用简短中文，空状态提供返回/刷新。
- 仅登录用户可提交；未登录时提示并引导登录。
