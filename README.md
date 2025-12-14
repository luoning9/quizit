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
- Quiz results page now reads `user_quiz_stats_view` to show template title/description, attempt count, and last score; missing params/run data show friendly states.
- Quiz list entries have both “查看” (results) and “开始” buttons in MainSelectPage.
- Markdown renderer supports table borders and renders Markdown/LaTeX; choice text auto-strips leading A./B. prefixes.
- back.answers accepts simple `["A"]` JSON and keeps math escapes intact in quiz templates.
- Database defaults: owner_id/user_id now rely on DB defaults (auth.uid()) for decks, cards, quiz_templates, quiz_runs, card_reviews; schema tightened (owner_id not null, cascade) and quiz stats view documented.
 
