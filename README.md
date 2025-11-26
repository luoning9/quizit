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
- Quiz results page shows friendly states for missing params or missing run data, fetches `quiz_template_stats` to display attempts/last score, and keeps a stats area.
- Quiz list now has both “查看” (results) and “开始” (take quiz) buttons in MainSelectPage.
- Markdown renderer supports tables with borders plus Markdown/LaTeX in prompts/answers; choice text strips leading A./B. prefixes.
- back.answers now accepts simple `["A"]` JSON and Quiz template parsing keeps math escapes intact.
 
