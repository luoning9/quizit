# AGENTS.md

## Project Overview

- Project name: `quizit`
- Type: Vite + React + TypeScript web app
- Backend/data layer: Supabase Postgres
- Main UI source: `src/`
- Database schema and SQL helpers: `docs/schema.sql`
- Python utility scripts: `local/`

## Common Commands

- All commands run in this repository should use the `quizit` conda environment.
- Preferred form: `conda run -n quizit <command>`
- Install dependencies: `conda run -n quizit npm install`
- Start dev server: `conda run -n quizit npm run dev`
- Build production bundle: `conda run -n quizit npm run build`
- Run lint: `conda run -n quizit npm run lint`
- Preview build: `conda run -n quizit npm run preview`

## Local Python Work

- Use the `quizit` conda environment for Python-based scripts.
- Preferred form for local script execution: `conda run -n quizit python3 <script>`.
- Python helpers and tests live under `local/` and `local/tests/`.

## Important Paths

- `src/pages/`: page-level React screens
- `src/components/`: shared React components
- `src/components/ui/`: reusable UI primitives
- `lib/`: shared frontend utilities
- `docs/`: SQL schema, prompts, specs, and reference material
- `tmp/`: generated artifacts and caches; do not treat as source

## Working Notes

- The Supabase RPCs and views defined in `docs/schema.sql` are part of the app's data flow.
- Keep changes focused; avoid touching unrelated files unless they are required for the task.
- When changing SQL logic, verify the corresponding frontend RPC call sites in `src/pages/`.
- Build warnings about large chunks are currently expected; a successful `npm run build` is still valid.
