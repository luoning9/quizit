请根据以下规范，为指定历史知识点生成 GraphViz DOT 文件，用于构建紧凑、美观、统一的小型知识图谱。

【全局布局要求】
- 使用 digraph，方向 rankdir=LR（从左到右）
- 图整体紧凑：nodesep=0.28，ranksep=0.45
- 使用 splines=true
- 全局字体：fontname="SimSun"，fontsize=14，minfontsize=14

【节点（node）样式】
- shape=box，style="rounded,filled"
- fillcolor="#FAFAFA"，color="#666666"
- fontname="SimSun"，fontsize=14
- margin="0.05,0.04"（极小内边距）
- 中心节点可以包含时间/身份说明
- 其他节点只写名称，不加任何解释

【节点前缀图标（纯 Unicode 黑白线条）】
只在“人物 / 组织 / 事件”节点前加图标：
- 人物（Person）：♙
- 组织（Organization）：⌂
- 事件（Event）：⬟
  其他类型（如思想、制度、条约等）不加图标。

【关系线（edge）样式】
- style=dashed（虚线）
- fontsize=14，labelfontsize=14（强制与节点一致）
- color="#444444"，arrowsize=0.6
- labeldistance=1.2
- 关系线标签长度为 2–10 字，要求简洁、自然、表达准确
  例如：提出、推动、参与、领导、奠基、促成、制定、产生影响等

【cluster 区域（动态自动分组）】
- 区域数量不固定，根据知识点关系自动生成 2–4 个组合合理的区域
- 可能的分组方式示例（根据知识点类型自动调整）：
  对事件：前因 / 背景；参与力量；直接结果；深远影响
  对人物：相关组织；参与事件；提出思想；历史影响
  对思想或制度：形成背景；提出者；影响事件；制度化影响
- cluster 样式：
  style="rounded,filled"
  color="#D0D0D0"
  背景色从以下淡色中任选（可重复）：#EEF8FF / #F2FFF2 / #F9F5E6 / #F4F0FF
- cluster 内部更紧凑：ranksep=0.25，nodesep=0.18
- cluster 标签简短明确（例：“参与的事件”“相关组织”“历史影响”）

【内容选择要求】
- 只包括与中心知识点具有直接关系的节点
- 关系必须符合历史逻辑（如创造、提出、参与、影响、促成、制定等）
- 图要紧凑、清晰、美观，适合在小图中呈现

【输出要求】
- 只输出 DOT 文件内容，不加任何解释、注释或额外文字
- 不使用代码块包裹 DOT，直接输出 DOT 纯文本

【任务】
请根据以上规范，为以下知识点生成 GraphViz DOT 文件：
（在此填写知识点名称与一句简短说明，例如：
“孙中山：资产阶级民主革命的领袖，创立兴中会、领导同盟会、提出三民主义，推动辛亥革命。”）
