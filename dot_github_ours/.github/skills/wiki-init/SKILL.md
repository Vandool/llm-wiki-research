---
name: wiki-init
description: >-
  First-time setup of the repository wiki, interactive only. Runs the question-and-answer flow,
  writes wiki/instructions.md and .github/wiki.config.json, generates the fact pages, proposes the
  module map for approval, integrates GitLab CI and hands over to the bootstrap driver. Use when the
  user asks to initialise, set up or bootstrap the wiki, or when wiki/instructions.md is missing or
  still the template. Never use for routine updates.
argument-hint: "[--resume] [--replan]"
allowed-tools: [read, edit, search, execute]
disable-model-invocation: true
---
# /wiki-init — first-time setup (interactive)

Procedure only. Authoring rules: `.github/instructions/wiki.instructions.md`; script flags:
`.github/skills/wiki-maintain/SKILL.md`. `S/<name>.py` below stands for
`python3 .github/skills/wiki-maintain/scripts/<name>.py`. **S<n>** = STOP: ask with `ask_user` and
wait for the answer. Nothing is written before S2; no structural change after S4 without asking.

## 0. Begin
- `S/run.py begin --mode init` (append `--resume` or `--replan` when given). It takes the lock and refuses
  when `wiki/instructions.md` is already customised unless one of those flags is present: report the
  refusal and stop.
- **No `ask_user` (`--no-ask-user`)**: print `wiki-init needs an interactive session: run
  WIKI_RUN=1 copilot --agent wiki-maintainer --model <models.bootstrap> and type /wiki-init`
  (fill the model from `S/config.py get models.bootstrap`), end with
  `WIKI-RUN-RESULT: {"status":"failed",…}` and stop. The fallback for every STOP below is this rule:
  the skill is interactive by definition.

## 1. Detect
`S/detect.py --json` → stack, source roots, exclusions, spec files, ADR directory, CODEOWNERS, remote
URL, default branch, branch candidates, existing CI and Pages jobs, available validators. Keep the
result; it pre-fills every default.

## 2. Questions — S1 per screen
Ask the five screens of `references/questions.md` (Identity, Stack, Content, Budget, Publish) with the
questions exactly as written, one `ask_user` per screen, every question pre-filled with its detected
default. Accept "ok" as "all defaults on this screen". Keep the answers as a flat
`{"Q1": …, …, "Q17": …}` object.

## 3. Brief and config — S2
- Fill `wiki/instructions.md` (installed from the template) from the answers: §1 identity, §2 audiences
  and language, §3 notes and spec paths, §4 concepts, §5 flows, §7 exclusions, §8 glossary seeds. Keep
  every section heading; a section without input keeps its `- …` line.
- Write the answers to `wiki/.init-answers.json`, then
  `S/config.py init --from .git/wiki/detect.json --answers wiki/.init-answers.json` and
  `S/config.py validate`. Show `git diff -- .github/wiki.config.json` and the filled brief.
- **S2**: approve or edit; apply edits and show again until approved.
- `S/facts.py --seed-catalog` (writes `wiki/catalog.yaml` only when absent).

## 4. Facts — S3
`S/facts.py --json` (all generators). Report the counts: files, symbols, routers, channels, ADRs,
dependency manifests. When the inventory is far above the guidance in
`.github/skills/wiki-maintain/references/budgets.md` (source bytes > 20 × `max_source_bytes_per_cluster`,
or thousands of files), propose extra exclusions, update §7 of the brief and `sources.exclude`, rerun.
**S3**: confirm the counts.

## 5. Module map — S4 (proposal only, no files)
- `S/plan.py build --json` proposes clusters from the module tree and the internal dependency graph,
  leaves first, sized to the cluster budget. Read `wiki/generated/inventory.md` and at most two
  entry-point excerpts (`S/excerpt.py <path> --lines 1-60`).
- Return a proposal only, writing no files: (a) the planned pages per folder, each with a title, one
  sentence of content and its `sources`; (b) "A rationale for what you deliberately do NOT give its own
  page"; (c) "The three places in the code you understand least".
- **S4**: "Wait for my approval. Revise the map after feedback and wait again." Approved →
  `S/plan.py commit --approved-by <user>` writes `wiki/.wiki-plan.json`; copy (b) into §6 and (c) into
  §15 "Known unknowns" of the brief.

## 6. Conventions — S5
`S/template.py Conventions` → draft `wiki/conventions.md` (≤150 lines): glossary seeded from §8 of
the brief plus the router, model and topic names found under `wiki/generated/` and `wiki/api/`,
`wiki/events/`; naming rules; the heading table per page type; the citation microformat; the
operational invariants you already saw in the entry points. **S5**: approve. After init the page is
`owner: both`.

## 7. CI integration — S6
- `S/ci_integrate.py detect --json`. Ask, pre-filled from Q14–Q17 and the detection: production branch,
  staging branch, dev previews, parallel deployments (Premium/Ultimate only). When a Pages job already
  exists, ask: (a) replace it with the wiki site, (b) keep it and set publish to false, (c) stop.
- `S/ci_integrate.py apply --prod-branch B [--staging-branch B] [--previews bool] [--parallel bool]
  [--publish bool] --dry-run` shows the diff. **S6**: approve → the same command with `--yes` →
  `S/ci_integrate.py check`; report which validator ran (glab, pyyaml or structural).
- `S/hooks.py status --json` confirms the git hooks (offer `S/hooks.py install` when missing);
  `S/index.py --write --consumers`.

## 8. Handover — S7
- Print `S/plan.py estimate` (credits) and the driver command
  `python3 .github/skills/wiki-maintain/scripts/bootstrap.py` (`--resume` after an interruption).
- **S7**: "Start the bootstrap driver now in the background?" yes → `S/run.py bootstrap --detach` (the
  driver starts once this session's lock is released); no → leave the command on screen.
- `S/log.py add --action Bootstrap --text "plan approved: N clusters, M pages"`, `S/run.py end`, prose
  summary, then the `WIKI-RUN-RESULT` line (`created`: `instructions.md`, `conventions.md`,
  `.wiki-plan.json`).

## --resume and --replan
`--resume`: skip screens already answered in the config and the brief; continue at the first incomplete
step (plan → conventions → CI → handover). `--replan`: keep brief and config, redo steps 5–8;
`plan.py commit` replaces the plan only while no cluster is `done`.
