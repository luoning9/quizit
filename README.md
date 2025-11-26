# Code Commit History

| Hash | Date | Message |
| --- | --- | --- |
| f5db4e6 | 2025-11-26 | feat: add quiz creation page and light/dark polish |
| 2391893 | 2025-11-26 | Refine button styling and unify usage |
| 00bb58e | 2025-11-25 | Update LoginPage again |
| 9175185 | 2025-11-25 | Update LoginPage |
| 76b6a7b | 2025-11-25 | Initial commit |
| 7349c19 | 2025-11-25 | Initial commit |

## Changes (Past Two Days)

- Added quiz creation page and polished light/dark theming across UI.
- Unified button styling for consistent look and feel.
- Refined Login page flows and copy.

## Latest Updates

- Added QuizResultPage (`/quiz-runs/:quizId/:runId`) and wired QuizRunPage to jump there after saving a run.
- Quiz results page shows friendly states for missing params or missing run data and keeps a stats placeholder area.
- Quiz list now has both “查看” (results) and “开始” (take quiz) buttons in MainSelectPage.
- Markdown renderer supports tables with borders plus Markdown/LaTeX in prompts/answers; choice text strips leading A./B. prefixes.
- back.answers now accepts simple `["A"]` JSON and Quiz template parsing keeps math escapes intact.

"某同学探究凸透镜所成实像的高度与焦距的关系时，记录了部分数据。根据表1（焦距$f_1 = 5 \text{cm}$）和表3（焦距$f_2 = 10 \text{cm}$）的数据，若将光源（物体）固定在距透镜 $40 \text{cm}$ 处，比较两焦距下所成实像的高度 $h_1$ 和 $h_2$，下列判断正确的是：[5, 6]\n\n表1 ($f_1 = 5 \text{cm}$):\n| 物距 $u/\text{cm}$ | 像高 $h/\text{cm}$ |\n| --- | --- |\n| ... | ... |\n| 40 | 0.5 |\n| ... | ... |\n\n表3 ($f_2 = 10 \text{cm}$):\n| 物距 $u/\text{cm}$ | 像高 $h/\text{cm}$ |\n| --- | --- |\n| ... | ... |\n| 40 | 1.1 |\n| ... | ... |",
       
