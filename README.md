## 生成历史知识点关系图（DOT）

历史知识点关系图由脚本 `local/gen_deck_dot_images.py` 生成。脚本会按 deck 中每张卡片的知识点，生成对应的 GraphViz `.dot` 内容，并上传到卡片资源 `back.dot`。

### 依赖

- `local/.env.local` 或环境变量中需要有：
  - `OPENAI_API_KEY`
  - `VITE_SUPABASE_URL`
  - `VITE_SUPABASE_ANON_KEY`

### 1. 创建或查看历史教材的 vector store

项目里用于管理 vector store 的脚本是 `local/openvs.py`。

列出现有 store：

```bash
python3 local/openvs.py list-stores
```

创建一个新的历史 store：

```bash
python3 local/openvs.py create-store --name "history"
```

查看某个 store 里的文件：

```bash
python3 local/openvs.py list-files --store-id vs_xxx
```

向 store 上传历史教材 PDF：

```bash
python3 local/openvs.py upload-file --store-id vs_xxx --file "/绝对路径/历史教材.pdf"
```

### 2. 生成某个 deck 的历史知识点关系图

`gen_deck_dot_images.py` 会：

- 按 `--title` 找到目标 deck
- 读取 deck 中的卡片
- 用卡片 `front/back` 作为知识点与说明
- 结合 `--store-id` 对应的教材资料生成 DOT
- 将结果缓存到 `tmp/dots/<card_id>.dot`
- 并上传到卡片资源 `back.dot`

运行命令：

```bash
python3 local/gen_deck_dot_images.py --title "某个 deck 标题" --store-id vs_xxx
```

可选参数：

- `--model`，默认 `gpt-5-mini`
- `--max-tokens`，默认 `8000`

示例：

```bash
python3 local/gen_deck_dot_images.py \
  --title "八下历史/第一单元/中华人民共和国的成立和巩固" \
  --store-id vs_xxx
```

### 3. 只复用本地缓存时

如果 `tmp/dots/<card_id>.dot` 已经存在，可以不传 `--store-id`。这时脚本不会重新调用 OpenAI，只会复用本地缓存并重新上传。

```bash
python3 local/gen_deck_dot_images.py --title "某个 deck 标题"
```

### 4. 结果查看

生成完成后：

- 本地缓存文件在 `tmp/dots/`
- 卡片资源中会出现 `back.dot`
- 在 app 的练习页和资源管理页中都可以预览 `.dot` 文件

## 生成地理地图引用（MAP）

地理卡片使用的不是直接生成图片，而是生成 `.map` 引用文件。脚本会根据卡片内容，从地理图册索引表中挑选相关图片，生成指向地图册 PDF 页面的引用信息。

### 索引表来源

地理图册图片索引表维护在：

- `docs/geography_8a_maps.md`

`local/gen_deck_map_refs.py` 会在运行时读取这个文件，并从表头 `章节标题,图片名称,页码,位置` 开始提取 CSV 内容作为 prompt 输入。

### 1. 生成某个地理 deck 的 `.map` 文件

运行命令：

```bash
python3 local/gen_deck_map_refs.py --title "某个地理 deck 标题"
```

可选参数：

- `--model`，默认 `gpt-5-mini`

示例：

```bash
python3 local/gen_deck_map_refs.py \
  --title "八上地理/第二章/中国的自然环境"
```

### 2. 生成逻辑

脚本会：

- 校验 `deck title` 中包含“地理”
- 读取 deck 中的卡片内容
- 从 `docs/geography_8a_maps.md` 中读取图册图片索引表
- 让模型为每张卡片挑选 1 到 3 张最相关的地图
- 将结果缓存到 `tmp/maps/<card_id>.map`
- 上传到卡片资源，文件名通常为 `back.map`，多张时为 `back0.map`、`back1.map` 等

`.map` 文件内容是 JSON，结构类似：

```json
{
  "map_file": "geo_8_1",
  "name": "中国主要河流和湖泊",
  "page": 13,
  "position": "主图"
}
```

### 3. 前端如何显示

前端会先读取卡片资源中的 `.map` 文件，再根据其中的：

- `map_file`
- `page`
- `position`

去大媒体存储中打开对应 PDF 页面：

```text
quizit_big_medias/maps/<map_file>/page_<page>.pdf
```

然后用 `position` 决定初始聚焦区域。

# Code Commit History

| Hash | Date | Message |
| --- | --- | --- |
| b60581f | 2025-12-25 | Add iconGhost button variant and enlarge deck edit icons |
| ab788d1 | 2025-12-25 | Add icon button variants for deck and quiz actions |
| 48c8040 | 2025-12-25 | Unify deck action icons and quiz list controls |
| 184b75f | 2025-12-25 | Add quiz material section with toggle |
| 61cc161 | 2025-12-25 | Update docs |
| 8728a3b | 2025-12-25 | Allow single-card JSON import |
| 304f045 | 2025-12-25 | Add deck resource manager and tighten markdown lists |
| eaacbe2 | 2025-12-24 | Avoid repeated stats backfill refresh |
| a8d17fa | 2025-12-24 | Update docs, practice page, and image script |
| 9bf085d | 2025-12-24 | Show full card ids in deck editor |
| 3b92934 | 2025-12-20 | Handle footer image notes for media hover |
| 3538466 | 2025-12-20 | add media notes |
| 81377fe | 2025-12-20 | Add image media support and updates |
| c7f9cfc | 2025-12-17 | Update biology prompt doc |
| 8eff25f | 2025-12-16 | Refine parseBack footer handling and make hover hint clickable |
| 88ca6be | 2025-12-16 | Add footer area on card back for secondary info |
| 5446ac3 | 2025-12-16 | Add generation prompts and deck map refs script |
| 0eb5b8d | 2025-12-16 | rebuild by gemini |
| b7d1db0 | 2025-12-16 | Fix StatsPage types and unused variables |
| 76000f0 | 2025-12-16 | Fix stats timezone details and link handling |
| cab058f | 2025-12-16 | Fix StatsPage date formatting for CN timezone |
| 13db2f8 | 2025-12-16 | Align stats with Beijing timezone and add stats nav |
| 26bf70d | 2025-12-15 | Add stats page using daily_user_stats and live compute |
| 0bffe42 | 2025-12-15 | Rename quiz_templates to quizzes and update frontend |
| 44e4dd1 | 2025-12-15 | Use soft delete for decks/quizzes and refresh view names |
| d3fdfe2 | 2025-12-15 | Soft-delete support and daily stats functions |
| 96fd29b | 2025-12-14 | Fix daily stats function return types |
| e475f7d | 2025-12-14 | Use belongs_to for card reviews |
| 23e918e | 2025-12-14 | Adjust review ownership fields |
| cf19582 | 2025-12-14 | Fix quiz question timing |
| 5be3965 | 2025-12-14 | Track card review time |
| b1a4cc9 | 2025-12-13 | Update docs and ignore rules |
| ce2a7df | 2025-12-13 | Reset deck stats and polish dialogs |
| d5190f3 | 2025-12-13 | Tweak viewer layout and media icons |
| e794c92 | 2025-12-13 | Adjust media modal layout and viewer height |
| 539dac8 | 2025-12-12 | Cache Supabase signed URLs in MapPdfViewer |
| 04d7d4d | 2025-12-12 | Adjust MapPdfViewer map loading |
| 2386bfe | 2025-12-12 | Update storage upload content type |
| 5187465 | 2025-12-11 | Adjust dot viewer sizing and cleanup |
| df4ce09 | 2025-12-11 | Show importing state on cards import |
| b9ca5d4 | 2025-12-11 | Add posOf3x3 control and update PDF test page |
| e97f788 | 2025-12-11 | Add PDF map viewer with grid navigation and tuning |
| a1de039 | 2025-12-10 | Improve deck import to update existing cards by id |
| 15a8edb | 2025-12-09 | Add quiz exit confirm dialog and form layout tweaks |
| 0e043b5 | 2025-12-09 | Adjust quiz create layout and deck flag for new quiz |
| 91c6441 | 2025-12-09 | UI icon tweaks and deck stats fixes |
| 326ac0a | 2025-12-08 | Use single user_deck_stats_view lookup in DeckStatus |
| 24994fd | 2025-12-08 | Prioritize low ease in fallback practice card selection |
| 4285a03 | 2025-12-08 | Refine AI dialog layout and safe choice prefix stripping |
| c3f189d | 2025-12-08 | Fix card selection prefix match and AI dialog layout |
| 1bb788d | 2025-12-08 | Update prompts docs and deck create wiring |
| 5e5886f | 2025-12-08 | Wire AI generation to edge function and add card sampling |
| 48860af | 2025-12-07 | Add CORS allow headers and show answer checking state |
| 862f37c | 2025-12-07 | Add OpenAI-backed edge check and inline edit UX tweaks |
| c6d0df6 | 2025-12-06 | Refine deck tree helpers and quiz result deck editing |
| b353760 | 2025-12-06 | Add secondary ghost button and deck progress bars |
| 563d4c0 | 2025-12-06 | Sort deck child nodes by numeric prefix |
| f58ef5c | 2025-12-06 | Add local image tooling and prompt update |
| 8998f2a | 2025-12-05 | Refine deck edit inline title/description UX |
| d91480e | 2025-12-05 | Improve quiz title/description inline editing |
| 36e14ff | 2025-12-05 | Clear sample JSON textarea on first real input |
| e90042f | 2025-12-05 | Adjust back parsing and flip hover text |
| 3e34010 | 2025-12-05 | Commit remaining local changes |
| 521f475 | 2025-12-05 | Add signed front media support to quiz prompt |
| 5efddaa | 2025-12-03 | feat: add local CLI for Google image generation |
| 6bf8df0 | 2025-12-03 | ui: set min width for quiz question area |
| c2bcdf3 | 2025-12-03 | feat: add Exit button beside progress ring |
| 68c9a83 | 2025-12-03 | chore: sync deck pages and quiz updates |
| 25893f2 | 2025-12-03 | fix: allow ref on Button component |
| 4ea3e1b | 2025-12-03 | chore: keep hover status visible when leaving card |
| 1a79a57 | 2025-12-03 | chore: refine Leitner selection and add decks owner/title index |
| 40cc61c | 2025-12-03 | chore: sync latest deck views and layout updates |
| e4a7689 | 2025-12-03 | refactor: reuse DeckList for new and due decks |
| 3c775a4 | 2025-12-03 | Add new decks page and update deck/user stats views |
| f5b0223 | 2025-12-03 | Adjust deck practice rendering and markdown font |
| b623772 | 2025-12-02 | Unify deck practice rendering and update leitner selection |
| b5cfe1a | 2025-12-02 | Refine deck status, quiz result UI, and Leitner selection |
| 0d66033 | 2025-12-01 | Add wrong book util, update quiz run stats and leitner selection |
| 543012a | 2025-11-30 | Update card reviews and stats on quiz submit |
| c0a054b | 2025-11-30 | Handle single-slot multi-blank answers in fill_in_blank check |
| dd14098 | 2025-11-30 | Tweak deck practice media status hover |
| c526d84 | 2025-11-30 | Adjust media hover hints and status display |
| be74935 | 2025-11-30 | Add Leitner practice selector and refine card stats trigger |
| 91851e3 | 2025-11-30 | Update card_stats trigger to always set updated_at and next_due |
| aa8fc64 | 2025-11-30 | Show dot media via modal icons with hover status |
| b8d6d6d | 2025-11-30 | set isBreak when reach cards count |
| 2b58fd1 | 2025-11-29 | Refine deck practice media hover and status UI |
| 06e6501 | 2025-11-29 | Tweak dot render background and deck practice toggling |
| b9c1454 | 2025-11-29 | Add dot render component and refine deck practice layout |
| ae2f36c | 2025-11-26 | chore: filter views by user and set auth defaults |
| 74318be | 2025-11-26 | chore: rely on auth defaults for ownership |
| c2a7ead | 2025-11-26 | feat: polish quiz results and stats display |
| 221295b | 2025-11-26 | docs: add database schema file |
| 70391e3 | 2025-11-26 | feat: add quiz result page and md/math polish |
| a934d2a | 2025-11-26 | feat: render markdown and math in quiz run |
| 4a5674a | 2025-11-26 | docs: add recent change summary |
| 1f120c0 | 2025-11-26 | docs: update README with commit log |
| f5db4e6 | 2025-11-26 | feat: add quiz creation page and light/dark polish |
| 2391893 | 2025-11-26 | Refine button styling and unify usage |
| 00bb58e | 2025-11-25 | Update LoginPage again |
| 9175185 | 2025-11-25 | Update LoginPage |
| 76b6a7b | 2025-11-25 | Initial commit |
| 7349c19 | 2025-11-25 | Initial commit |
 
