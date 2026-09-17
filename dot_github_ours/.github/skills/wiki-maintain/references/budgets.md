# Context budget rules

Values come from `budgets` in `.github/wiki.config.json` (`config.py get budgets.<key>`); the scripts
meter them into `.git/wiki/run.json`. Roughly 12 tokens per line, 4 bytes per token.

## Reading order (every mode)
1. `wiki/index.md` (≤120 lines).
2. At most 2 folder indexes (≤200 lines each; sharded `index-a-m.md` count as one).
3. At most 5 pages. Update: only the work list, ≤ `max_pages` (8). Lint: ≤ `lint_sample_pages` (10).
   Page: `conventions.md`, `glossary.md`, ≤3 dependency pages. Query: the 5 best matches.
4. Code only through declared `sources` and the hunks `affected.py` lists, via `excerpt.py`.
5. `log.md` never, unless debugging the wiki (last 20 entries).

## Rules
| Rule | Value / mechanism |
|---|---|
| Sources | Only declared `sources` and the hunks `affected.py` lists; `excerpt.py --hunks` (±20 lines), `--symbol NAME`, `--lines a-b` |
| Whole-file reads | `cat`/`less`/`more` denied; the read tool is denied for files > `read_max_bytes` (64 KB) or > 400 lines without a range (the denial names `excerpt.py`) |
| Excerpt size | `max_excerpt_lines` (120) per call, `max_excerpt_lines_per_run` (800) per run |
| Per-run budget | `max_source_bytes_per_run` (200 KB ≈ 50k tokens), metered by `excerpt.py` and the post-tool hook into `run.json.bytes_read`; exceeded ⇒ `excerpt.py` exit 3 and the guard denies further reads with "budget exhausted: defer" |
| Per-cluster budget | `plan.py build` sizes clusters to ≤ `max_source_bytes_per_cluster` (120 KB) and ≤ `max_pages_per_cluster` (6); splits by sub-directory, then by dependency-graph file groups; an over-budget single file gets `#La-Lb` ranges from its top-level symbols |
| Over budget | write nothing more, `run.py defer --reason "…"`, result line `deferred`; `/wiki-page` also `plan.py mark <id> deferred`; the driver re-splits once (`plan.py split`) before giving up |
| Injected context | `session_context_kb` (30 KB) at session start; overflow is replaced by "see run.py status" |
| Requests | ≤ `max_requests_per_run` (5) OPEN lines, ≤ `max_request_chars` (500) each, oldest first |
| Time | `run_timeout_s` (1200) per update session, `bootstrap_timeout_s` (1800) per cluster; the driver kills the process group afterwards, so finish pages early rather than late |
| Instruction files | copilot block ≤40 lines, `wiki.instructions.md` <150, `wiki/instructions.md` ≤300, `conventions.md` ≤150 (L04) |

## Page size caps (L04, body lines)
Overview 150 · Architecture 200 · Module 200 · Concept 120 · How-to 120 · Contract 400 · Contract Guide 150
· Runbook 150 · Glossary 300 · Feature 80 · Capability Map 150 · Release Notes 200 · What Changed 60
· Analysis 200 · Generated 400 · Conventions 150 · Requests 400 · Instructions 300.

## Why
A stale wiki is worse than none, and an agent cannot notice its own staleness; bounded, evidence-first
reading keeps every statement traceable to code that was actually read in this run, keeps headless runs
inside a fixed credit budget, and makes a failed run resumable: partial lint-clean work is kept, the
rest is deferred with a reason rather than guessed.
