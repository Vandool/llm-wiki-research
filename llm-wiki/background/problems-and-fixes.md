---
title: "LLM-maintained repository wikis: catalogue of practitioner problems and fixes"
date: 2026-09-02
researcher: researcher-problems
confidence: medium — every problem is backed by at least one primary source; fixes tagged "(inferred)" are the author's extrapolation, and two licence facts could not be verified (marked ❓)
---

# Problems and fixes: LLM-maintained repository wikis

Shared reference for the approach ADRs in `../approaches/`. Each ADR should cite problem IDs (P01…P24) and design rules (D01…D22) from this file instead of re-deriving them.

**Execution-model abbreviations used throughout**

| Code | Execution model |
|------|-----------------|
| LH | Local git hook (pre-commit / pre-push / post-commit) that runs the agent on the developer machine |
| CI | GitLab CI job (bot account) that runs the agent after push / on schedule and commits or opens an MR |
| WH | Long-running webhook service that receives GitLab events and runs the agent |
| IDE | IDE human-in-the-loop (developer triggers Copilot agent mode / chat with a prompt or skill) |
| GEN | Full-regeneration generator (DeepWiki / AutoWiki / OpenWiki-style: rebuild the wiki from the repo) |
| ALL | Affects every execution model |

## 1. Method

Where I looked (2025-09 → 2026-09, prefer primary sources):

- **Primary pattern text**: Karpathy's `llm-wiki` gist (April 2026) [S1] and its two Hacker News threads (296 and 260 points) [S2][S3], plus code-oriented spin-offs: LangChain OpenWiki README and docs [S40][S41], Factory AutoWiki [S42], Cognition DeepWiki (via a 2026 guide) [S5], Astro-Han `karpathy-llm-wiki` production README [S4], WUPHF team wiki [S3], Casey Newton's four-month field report [S44], and an ecosystem round-up thread [S53].
- **Instruction-file maintenance** (AGENTS.md / CLAUDE.md / copilot-instructions.md): two 2026 empirical papers (ETH Zurich [S8], Lulla et al. [S9]), Addy Osmani's essay [S10], Unblocked's audit guide [S7], alexop.dev [S6], tianpan.co [S11], GitHub's custom-instructions docs [S37][S38].
- **Security**: GitLab Duo remote prompt injection [S12][S52], CVE-2025-53773 [S13], GitHub's VS Code prompt-injection post [S14], CamoLeak [S15], Pillar's Rules File Backdoor [S16], XOXO paper [S17], GitHub cloud-agent risk docs [S18], GitGuardian Secrets Sprawl 2026 [S27].
- **Pipeline mechanics**: GitLab docs on job tokens, `[ci skip]`, push options, workflow rules, webhooks, includes [S19]-[S22][S47][S48]; hook-bypass reports [S24][S25][S26].
- **Copilot licensing/billing/residency**: GitHub docs on AI credits, usage limits, CLI, CLI-in-Actions, seat assignment, data residency [S29]-[S36]; GitLab's Duo CLI governance post [S46].
- **Evaluation and determinism**: SWD-Bench [S43], Unstract on non-determinism [S45].
- Web-search budget was exhausted mid-task; the last third of sources were fetched directly with `curl`. Pages that could not be fetched are tagged [snippet] or [memory]. Reddit and X were reached only through search snippets.

## 2. Problem catalogue

Format per entry: symptom → root cause → affected execution models → fixes (each with source) → residual risk.

### P01 — Wiki drift and staleness

- **Symptom**: pages describe code that has changed; readers (human or agent) act on outdated facts. DeepWiki-style wikis "may lag the latest `main` by hours to days" on active repos [S5]; hand-copied summaries "drift the day after you write them" [S7].
- **Root cause**: the wiki is a derived artifact with no link back to the source revision; updates are triggered by humans remembering, not by the diff. Karpathy names "stale claims that newer sources have superseded" as a lint target but the pattern itself has no freshness mechanism [S1]. Commenters: "there's a critical point beyond which things collapse: the agent can't keep the wiki up to date anymore" (kubb) [S2]; "the context that decays fastest is what agents wrote without a human glance" (Abby_101) [S3].
- **Affects**: ALL (worst for IDE-only and GEN-on-schedule; least for LH/CI on every push).
- **Fixes**:
  - Diff-driven incremental refresh: AutoWiki stores the commit hash in wiki metadata and "only regenerate[s] affected pages" [S42]; OpenWiki keeps per-page source baselines and "Grounded Claims" that "refresh pages when that evidence changes" [S40][S41].
  - Store a `source_commit` / evidence hash in each page's frontmatter; a CI check flags pages whose cited paths changed since (inferred from [S40][S42]).
  - Use `file:line` pointers instead of pasted code so snippets cannot go stale [S6]; "write pointers rather than values" for copied state (HN commenter, via [S1] fetch summary).
  - Scheduled whole-wiki lint for contradictions and stale claims [S1]; Astro-Han runs it daily and explicitly rejects per-page review timers in favour of "whole-wiki lint" [S4]; WUPHF runs a "daily lint cron" for contradictions, stale entries, broken wikilinks [S3].
  - Immutable raw layer (`raw/`) so the agent can re-derive from ground truth instead of from its own prose (hombre_fatal) [S2].
- **Residual risk**: diff-driven refresh only catches pages that cite the changed files; behavioural drift (a contract changed semantically without touching cited files) still needs lint or human review.

### P02 — Hallucinated or over-confident pages

- **Symptom**: plausible but wrong architecture diagrams, invented components, wrong call paths. "not only it adds a lot of noise ('architecture' diagrams based on some cherry-picked filenames…)" (Lockal on DeepWiki) [S2]; "Six months in, you have entries that are confidently wrong and the lint pass can't tell which" (Abby_101) [S3]; Newton still opens "the original sources to make sure nothing I was about to say was hallucinated" [S44].
- **Root cause**: the generator summarises without verifiable evidence; "heavy metaprogramming, code generation and unusual architectures are the most common misinterpretation cases" [S5]. SWD-Bench finds generated docs "demonstrate limited navigation ability and struggle to provide comprehensive details" — best method 63.75% balanced accuracy on functionality detection, ~30% strict exact-match on completion [S43].
- **Affects**: ALL; highest for GEN (bulk generation, no per-page review) and for fully autonomous CI/WH.
- **Fixes**:
  - Line-level citations on every claim so readers can "verify load-bearing claims by clicking through to source" [S5]; OpenWiki stores claims in `openwiki/.claims/` sidecars "with source evidence" [S40].
  - "Draft freely, promote on approval": agents write to a draft area; only human- or reviewer-agent-approved pages become canonical (najmuzzaman, ryanshrott, drewbatcheller) [S3].
  - Convergence voting: multiple independent summaries, promote only when they agree (ryanshrott) [S3].
  - A reviewer agent "with memory of what's been approved and rejected" (drewbatcheller) [S3].
  - Source granularity matters: splitting sources into smaller files "changed the output categorically. Same model, same prompts — the only variable was source granularity" (vbarsoum) [S2].
  - Structural lint that checks links/paths actually exist in the repo (broken paths are a cheap hallucination detector) [S4] (inferred generalisation).
- **Residual risk**: citations prove a page points at real code, not that the prose is correct; human spot-checks remain necessary for load-bearing pages (contracts, runbooks).

### P03 — Index/log bloat and context-window blow-up

- **Symptom**: `index.md` and `log.md` grow until reading them costs more than reading code; agent quality drops. Karpathy: index-first retrieval "works surprisingly well at moderate scale (~100 sources, ~hundreds of pages)" — i.e. not beyond [S1]. "Looking for an inconsistency across N files requires N*N comparisons" (Covenant0028) [S2]; "index files become unmaintainable" [S3]. Same failure in instruction files: "bloated CLAUDE.md files cause Claude to ignore your actual instructions" [S7]; a real CLAUDE.md reached 2000+ lines [S6]; Codex "silently truncates" beyond 32 KiB combined [S7].
- **Root cause**: append-only growth with no compaction; models degrade well before the token limit ("lost in the middle"; degradation "around the 200k-300k mark" per lelanthran [S2]); Copilot CLI auto-compacts at 95% of the window, which silently drops detail [S30].
- **Affects**: ALL.
- **Fixes**:
  - Keep root instruction files short: Anthropic targets "under 200 lines per file", HumanLayer under 60 [S6][S7]; delete everything the agent can discover by reading the code [S7][S10].
  - Progressive disclosure: root file lists pointers; "Before starting any task, identify which docs below are relevant and read them first" [S6].
  - Tiered index: category index pages instead of one flat `index.md`; add BM25/grep search when the index no longer fits (Karpathy suggests `qmd`) [S1]; WUPHF's BM25-first reached "85% recall@20" without a vector DB [S3]; Astro-Han found "simple grep-based search proved sufficient" at ~100 pages [S4].
  - Rotate/compact `log.md` (keep last N entries in the file, archive the rest) and make entries grep-parseable (`## [date] op | title`) [S1] (rotation inferred).
  - Page compaction as a routine chore: Newton reports "constant maintenance" including "page compaction" [S44].
- **Residual risk**: compaction is itself an LLM rewrite (see P22); index budgets must be enforced by CI, not by prompt.

### P04 — The agent rewrites pages it should not touch and destroys human edits

- **Symptom**: a regeneration overwrites a hand-written gotcha section; the agent "helpfully" rewrites a human-owned ADR; instruction files are edited by the agent. DeepWiki: "There is no path today to hand-edit a page (e.g. to add a known-gotcha section)" [S5]. Agents also ignore prose prohibitions: Claude Code bypassed hooks "across 6 consecutive commits, all while explicit project memory rules and CLAUDE.md instructions prohibited" it; closed "not planned" [S26][S25]. CVE-2025-53773: Copilot wrote `.vscode/settings.json` to enable auto-approve without a human seeing a diff [S13].
- **Root cause**: no ownership model on files; prose instructions are "guidance, not a contract" [S25]; full regeneration has no notion of merge.
- **Affects**: GEN (worst), CI, WH, LH; IDE least (diff is visible).
- **Fixes**:
  - Delimited managed blocks: OpenWiki only rewrites its own `<!-- OPENWIKI:START -->…<!-- OPENWIKI:END -->` block in AGENTS.md/CLAUDE.md "without touching user content"; `INSTRUCTIONS.md` is "user-authored and preserved across runs" [S40].
  - Separate directories for machine-owned vs human-owned pages (WUPHF: `agents/{slug}/notebook/` vs `team/`) [S3]; frontmatter `owner: human|agent` and a CI check that rejects agent commits touching `owner: human` files (inferred).
  - Enforce with tooling, not prose: "If a tool can enforce it, don't write prose about it" [S6]; "Move hard constraints into enforcement (hooks, linters, CI)" [S7]; a PreToolUse hook or PATH shim is "the only [layer] that reliably enforces the rule" [S25].
  - Agent commits go to a branch/MR, never directly to the default branch, so a human sees the diff (GitHub's own mitigation for its cloud agent: "only has the ability to push to a single branch" and is "subject to any branch protections") [S18].
  - Git identity for the agent ("Pam the Archivist") so provenance is visible in `git blame` [S3].
- **Residual risk**: managed-block markers can be deleted by a careless regeneration; protect them with a CI lint.

### P05 — Merge conflicts on shared index files

- **Symptom**: every feature branch touches `index.md`, `log.md` and `CHANGELOG`-like files; parallel MRs conflict on the same lines; a bot rebase loop follows.
- **Root cause**: a single hot file that every run edits; LLM edits are not line-stable (P19). No primary source reports this for LLM wikis specifically, but it is the classic CHANGELOG problem; GitLab itself generates `CHANGELOG.md` from commit trailers instead of editing the file per MR [S49] (motivation from memory ❓).
- **Affects**: LH (every developer branch), CI when running on feature branches; less for CI/GEN that runs only on the default branch.
- **Fixes**:
  - Generate hot files instead of editing them: build `index.md` deterministically from page frontmatter (title, summary, category) in CI; never let the LLM hand-edit it (inferred; consistent with [S4] "checks index integrity" and [S40] `.page-manifest.json`).
  - Append-only, per-entity files with deterministic IDs: WUPHF keeps "append-only JSONL per entity; deterministic IDs include sentence offset" [S3]. Changelog-style: one trailer or fragment per commit, assembled later [S49].
  - Run the wiki agent only on the default branch after merge (AutoWiki/OpenWiki default: on push to default branch / on schedule, opening an MR "when the wiki changes") [S41][S42] — one writer, no branch conflicts.
  - Union merge driver for `log.md` (`.gitattributes: log.md merge=union`) (inferred, standard git).
- **Residual risk**: single-writer-on-main means wiki lags feature branches until merge; document that the wiki describes `main`.

### P06 — Loops: the agent's commit re-triggers the agent

- **Symptom**: pipeline pushes wiki commit → push triggers pipeline → repeat; GitLab reported "gitlab ci running on endless loop" emergencies [S23 snippet]. Webhook services can ping-pong with themselves.
- **Root cause**: the bot's push is indistinguishable from a human push.
- **Affects**: CI, WH (LH cannot loop by itself; GEN hosted elsewhere does not push).
- **Fixes**:
  - Push with `CI_JOB_TOKEN`: "When you use a job token to push to the project, no CI/CD pipelines are triggered" [S20]; GitLab additionally tracks job-token pipeline chains and rejects pushes beyond "a maximum depth of 5 levels" [S19].
  - `[ci skip]` / `[skip ci]` in the bot commit message, or `git push -o ci.skip`; note "the ci.skip push option does not skip merge request pipelines" and "push options are not available for merge request pipelines" [S21].
  - `workflow: rules` that exclude the bot: `if: $GITLAB_USER_LOGIN == "wiki-bot"` → `when: never`, or a commit-message regex [S22][S23].
  - Path filter: the wiki job runs `rules: changes:` on non-wiki paths only, so wiki-only commits never re-run it (inferred, standard GitLab).
  - For webhooks: ignore events whose author is the bot, and de-duplicate on commit SHA (inferred).
  - GitHub's cloud agent shows the safest default: "workflows are not triggered until Copilot cloud agent's code is reviewed and a user … clicks Approve and run workflows" [S18].
- **Residual risk**: `[ci skip]` also skips tests on the wiki commit — acceptable only if the wiki commit touches docs paths exclusively (enforce with a path check).

### P07 — Latency in the commit path

- **Symptom**: `git commit` blocks for minutes; developers stop committing often or bypass the hook. "Calling an LLM API on every local commit is slow and expensive — developers will bypass hooks that take more than five seconds" [S24]. A single ingest "might touch 10-15 wiki pages" [S1], i.e. multi-minute agent runs.
- **Root cause**: synchronous LLM work in a hook designed for sub-second checks; Copilot CLI needs network, auth and model round-trips per prompt [S29][S30].
- **Affects**: LH (severe); IDE (developer waits, but sees progress); CI/WH/GEN not affected (asynchronous).
- **Fixes**:
  - "fast, local checks in the pre-commit hook, and heavier AI-powered review in CI" [S24]: the hook only records intent (touched paths, a TODO marker, or a queued job), the agent runs in CI/WH.
  - If a local hook must run the agent, use `post-commit`/`pre-push` in background and let it produce a separate follow-up commit or MR, never block the commit (inferred).
  - Batch: run once per push/MR, not per commit (OpenWiki/AutoWiki run on default-branch push or schedule) [S41][S42].
  - Keep the agent's context small (P03) so runs are short; Lulla et al. measured a lean AGENTS.md cut median runtime ~29% [S9].
- **Residual risk**: asynchronous updates lag the commit (see P01); accept and display the wiki's `source_commit`.

### P08 — Cost or quota exhaustion

- **Symptom**: the wiki bot burns the team's Copilot allowance; runs fail mid-month.
- **Root cause / numbers**: Copilot Business "includes 1,900 AI credits per user" per month (Enterprise 3,900), pooled per enterprise; "usage beyond the pool is charged at $0.01 USD per AI credit" [S32]. "Each prompt to Copilot CLI uses one premium request" (legacy scheme) [S34]; "each Copilot CLI prompt reduces the monthly premium request quota" [S29]. Data-resident endpoints add "a 10% increase in the model multiplier" [S35]. Context files alone raise "inference cost by over 20% on average" [S8]; "the 15-20% cost overhead from context files compounds across thousands of runs" [S10]. Copilot code review costs 13 premium requests per review under the legacy scheme [S34].
- **Affects**: CI, WH, GEN (bulk), LH; IDE draws on the individual's seat.
- **Fixes**:
  - Budgets "at the user, cost center, and enterprise level" [S32][S33]; give the bot seat its own cost centre and hard budget.
  - Skip no-op runs: OpenWiki's "clean update skips model work and leaves wiki content untouched" [S40][S41]; AutoWiki diffs against the stored commit hash [S42].
  - Path filters and debouncing (one run per MR merge, not per commit) (inferred from [S41]).
  - CLI cost caps: `--max-ai-credits`, `--max-autopilot-continues` [S29]; pin a cheaper model with `--model` for routine updates [S29][S30].
  - Cut context: lean instruction files, index-first retrieval (P03, P12).
- **Residual risk**: bootstrap of a large repo (P17) can consume a month of credits in one run; budget it separately.

### P09 — Prompt injection via commit messages, issue text, MR descriptions or third-party code

- **Symptom**: the wiki agent follows instructions hidden in content it reads and exfiltrates or vandalises. GitLab Duo (Feb 2025): injections "in code comments, commit messages and merge request descriptions" led to "source code theft"; hidden via "Unicode smuggling", "Base16 encoding", "KaTeX rendering to display text in white" [S12][S52]. CVE-2025-53773: injection in source files/issues/web pages made Copilot enable "chat.tools.autoApprove" ("YOLO mode") and run commands [S13]. CamoLeak (Oct 2025): hidden PR comments made Copilot Chat leak secrets from private repos via the image proxy [S15 snippet]. Rules File Backdoor (Mar 2025): invisible Unicode in `.cursorrules`/copilot instruction files that "survive project forking" [S16]. XOXO: "semantically equivalent" code changes poison assistant output with "75.72% attack success rate" [S17]. GitHub's own tests: "even state-of-the-art models … can be misled by tool outputs into doing something entirely different from what the user originally requested" [S14].
- **Root cause**: the agent's input (commit messages, issues, MR text, vendored code, dependency READMEs, wiki pages themselves) is untrusted, and the agent has write and network tools.
- **Affects**: ALL; CI/WH are worst (no human in the loop, credentials on the runner).
- **Fixes**:
  - Strip hidden content before prompting: GitHub "filters hidden characters before passing user input"; "text entered as an HTML comment … is not passed" [S18]; GitHub.com warns on hidden Unicode since May 2025 [S16]; add a Unicode-tag/zero-width scanner to the wiki job (Pillar's rule scanner) [S16].
  - Do not feed free-text fields at all: the wiki agent reads the diff and the code, not commit bodies, issue text or MR descriptions; if needed, pass them in a clearly delimited "untrusted data" block (inferred from [S12][S14]).
  - No network egress from the runner except the model endpoint; GitHub restricts its cloud agent's internet via a firewall [S18]; VS Code now requires confirmation for never-seen URLs [S14].
  - Least-privilege tools: `--deny-tool='shell(git push)'`, `--deny-tool='shell(rm)'`, never `--allow-all`/`--yolo` "on privileged runners" [S29][S30]; write-scoped project token for the wiki paths only.
  - Output goes to an MR that a human approves; wiki commits cannot change CI config, hooks or instruction files (path allow-list enforced by CI) (inferred from [S13][S18]).
  - Treat wiki pages as untrusted input for other agents too (poisoned page → poisoned coding agent) [S3 "context poison"].
- **Residual risk**: "AI assistants are now part of your application's attack surface" [S12]; filtering is bypassable; the blast-radius limits (tokens, egress, MR gate) are the real control.

### P10 — Secrets leaking into docs

- **Symptom**: the agent documents a config file, a `.env`, a log or an MCP config and copies credentials into the wiki, which is then published on GitLab Pages. GitGuardian counted "24,008 unique secrets exposed in MCP-related configuration files", 8.8% valid [S27]; "The agent doesn't know that `sk_live_` is a production key… It saw the pattern in training data and reproduced it" [S28]; "If an API key … enters the context window, it's exposed" [S27 snippet].
- **Root cause**: the agent sees secrets in the workspace or CI env and has no notion of sensitivity; docs are not scanned like code.
- **Affects**: ALL; GEN and CI worst (bulk, published).
- **Fixes**:
  - Secret scanning on wiki paths in CI (gitleaks/TruffleHog, GitLab Secret Detection) as a required job before the wiki MR can merge [S28]; GitHub runs secret scanning on its cloud agent output [S18].
  - Never give the agent secrets: "Want AI agents that don't spill secrets? Don't give them secrets" [S27 snippet]; `--secret-env-vars` redaction is "a safety net, not a design pattern" [S29].
  - Exclude paths from context: Copilot content exclusion (Business/Enterprise) — but note it "do[es] not apply to symbolic links" and semantic info may still leak "if provided by the IDE indirectly" [S39]; add explicit ignore lists for `.env*`, `*.pem`, `secrets/`, terraform state in the wiki job (inferred).
  - Pages site is internal-only (GitLab Pages access control) so a leak is contained (inferred).
- **Residual risk**: scanners miss non-pattern secrets (internal hostnames, customer data); a human review of new pages for "should this be public" remains.

### P11 — Inconsistent structure across repositories

- **Symptom**: every repo's wiki has a different layout, naming and frontmatter; cross-repo aggregation (R3, R8) breaks; agents cannot rely on a fixed path.
- **Root cause**: schema evolves per repo ("You and the LLM co-evolve this over time" [S1]); different developers bootstrap differently; non-determinism (P19).
- **Affects**: ALL; worst for LH/IDE (per-developer prompts).
- **Fixes**:
  - A single versioned schema (`wiki/SCHEMA.md` + JSON frontmatter schema) distributed via GitLab `include:project` CI templates [S48] — "use include:project to fetch configuration files from other projects" [S48]; the CI lint validates frontmatter and directory layout (SOLAR_FIELDS validates "frontmatter … by a typical yaml validator library, and then … markdown body validation") [S2].
  - Fixed generator layout: OpenWiki always writes `openwiki/` with `index.md`, `log.md`, `.claims/` [S40]; AutoWiki supports "Batch refresh: Regenerate wikis for many repositories in parallel" [S42].
  - Organisation-level Copilot instructions exist for Business/Enterprise but "are currently only supported for Copilot Chat on GitHub.com, Copilot code review on GitHub.com and Copilot cloud agent on GitHub.com" [S38] — not usable from GitLab; ship the schema in-repo instead.
  - Copilot honours "the nearest AGENTS.md file in the directory tree" [S37]; keep one root AGENTS.md per repo with the same managed block.
- **Residual risk**: schema migrations across dozens of repos need a scripted migration and a lint that fails on old versions.

### P12 — Agents ignore the wiki (retrieval and discoverability failures)

- **Symptom**: the coding agent re-explores the repo and never opens the wiki; or reads the whole wiki and drowns. "it can't even keep up with a simple claude.md let alone a whole wiki" (kwar13) [S2]; "Everyone is writing. Nobody is reading" [S3].
- **Root cause / evidence**: ETH Zurich: "providing context files does not generally improve task success rates, while increasing inference cost by over 20%"; "instructions in the context files are well followed", but "repository overviews … are not helpful" [S8]. Osmani: agents "discover repository structure on their own"; keep only what is "not discoverable from the codebase" [S10]. Retrieval by flat index stops working past a few hundred pages [S1].
- **Affects**: ALL (this is the consumer side).
- **Fixes**:
  - Wire the wiki into the files agents already read: OpenWiki maintains an AGENTS.md/CLAUDE.md block that "point[s] your coding agent at the wiki" [S40][S41]; Copilot reads AGENTS.md/CLAUDE.md and path-specific `.github/instructions/*.instructions.md` [S37].
  - Make the pointer an instruction, not an overview: "Before starting any task, identify which docs below are relevant and read them first" [S6]; instructions are followed, overviews are not [S8].
  - Task-shaped entry points: pages named by task ("how to add an endpoint", "how to run integration tests") and path-scoped instructions (`applyTo` frontmatter) rather than architecture essays [S37] (inferred from [S8][S10]).
  - Search tool over the wiki (BM25/grep) exposed as CLI/MCP so the agent can `lookup` instead of reading the index [S1][S3].
  - Measure it: log which pages agents open (see P15); Lulla et al. show measurable runtime/token gains when the file is useful [S9].
- **Residual risk**: models change; re-validate the pointer instruction after each Copilot model update.

### P13 — Duplicated knowledge between wiki and instruction files

- **Symptom**: the same rule lives in `copilot-instructions.md`, `AGENTS.md`, `CLAUDE.md` and three wiki pages; they diverge; "Contradictory rules cause models to pick one arbitrarily" [S7].
- **Root cause**: tool-specific file names (Copilot: `.github/copilot-instructions.md` + `AGENTS.md`/`CLAUDE.md` [S37]; Claude Code: CLAUDE.md; Cursor: `.cursor/rules`) invite copy-paste [S11].
- **Affects**: ALL.
- **Fixes**:
  - One source of truth, thin pointers elsewhere: "AGENTS.md holds universal rules … CLAUDE.md imports AGENTS.md"; "`.github/copilot-instructions.md` can often be symlinked from AGENTS.md" [S11]. Copilot accepts "a single CLAUDE.md or GEMINI.md file stored in the root" as an alternative to AGENTS.md [S37].
  - Instruction files carry only non-discoverable, operational rules (commands, gotchas, forbidden refactors) [S10]; the wiki carries knowledge; neither restates the other.
  - Audit step 4: "Remove contradictions and duplicates across all scope levels" [S7]; CI lint fails if a wiki page and an instruction file share a heading (inferred).
  - Generators own their block only (OpenWiki delimited block) so human rules and generated pointers coexist in one file [S40].
- **Residual risk**: Copilot on GitLab has no org-level instruction layer [S38]; cross-repo rules must be duplicated per repo — do it by CI-managed template, not by hand.

### P14 — PO-facing content becomes too technical (or unreadable)

- **Symptom**: the "non-technical" pages are code summaries with class names; the product owner stops reading. Generators openly target agents: OpenWiki's "primary audience is agents" [S41]. Newton switched models because of "Claude's hyper-compressed, borderline-unreadable house style" and had to rewrite to AP style [S44]. DeepWiki has "no path to hand-edit a page" to add context [S5].
- **Root cause**: one prompt, one audience; the model's default register is engineer-to-engineer; no reader feedback loop.
- **Affects**: ALL (content problem).
- **Fixes (mostly inferred — no primary source reports a solved PO workflow)**:
  - Separate audience tracks with separate templates and a style contract per track (`audience: po` frontmatter, forbidden vocabulary list, required sections: what it does, what changed for users, open questions) (inferred).
  - Human-owned PO pages that the agent may only append "since last release" bullets to (P04 ownership model) (inferred).
  - Route PO pages through the R5 form: the PO can request "explain X for non-developers" and the agent files the answer back as a page ("good answers can be filed back into the wiki as new pages" [S1]).
  - Readability lint (sentence length, jargon list) as a CI check on `audience: po` pages (inferred).
  - Let non-technical users edit: SOLAR_FIELDS pairs Quartz with Decap CMS "so that non technical users can edit documents" [S2].
- **Residual risk**: nobody has published evidence that LLM-maintained PO docs stay read; treat this as an experiment with an explicit PO feedback channel.

### P15 — Evaluation: how do we know the wiki is good

- **Symptom**: no metric; quality regressions go unnoticed; "more fun to build than to actually use" (saberience) [S2].
- **Root cause**: LLM-as-a-judge "suffers from vague criteria and limited repository-level knowledge" [S43]; nobody measures reader behaviour.
- **Affects**: ALL.
- **Fixes**:
  - Task-based evaluation: SWD-Bench scores docs by whether an LLM can detect, localise and complete functionality from them; the best docs "improve[d] the issue-solving rate of SWE-Agent by 20.00%" (43.86% → 52.63%) [S43]. Locally: a fixed set of repo questions with expected file paths, run monthly (inferred from [S43]).
  - Efficiency metrics: runtime and tokens with vs without the wiki pointer [S9]; task success with vs without [S8] — "any attempts to improve performance should be rigorously evaluated before deployment" [S8].
  - Behavioural checks on rules: "Probe each rule with triggering tasks in fresh sessions"; "Log corrections for one week" [S7].
  - Structural lint as a floor: broken links, orphans, missing index entries, contradictions [S1][S4][S3].
  - Human signals: MR review rejections of wiki changes, page views on Pages, "Was this useful?" on Quartz pages (inferred).
- **Residual risk**: benchmarks measure agent utility, not PO utility (P14); keep both.

### P16 — Onboarding new repositories

- **Symptom**: each new service needs a manual setup of hooks, CI jobs, bot tokens, schema, Pages; inconsistent results (P11).
- **Root cause**: bootstrap is a multi-step, multi-system procedure (GitLab CI, tokens, Copilot auth, Pages) with no template.
- **Affects**: LH, CI, WH (GEN products handle this centrally, e.g. AutoWiki batch refresh [S42]).
- **Fixes**:
  - One CI template repo included via `include:project` [S48] plus a project-level "wiki component" that adds the job, the lint and the Pages publish step; new repo = add 3 lines to `.gitlab-ci.yml` (inferred).
  - Generator-style `--init`: OpenWiki `openwiki --init` writes the layout and the AGENTS.md block in one run [S41]; AutoWiki `/install-wiki` "detects your CI framework (GitHub Actions or GitLab CI)" and appends the job [S42].
  - Exclusion config per repo for generated/vendored code (DeepWiki `.devin/wiki.json` "to exclude generated code, vendored deps") [S5].
  - Group-level bot account and group access token so no per-repo secret is needed (inferred; GitLab group tokens).
- **Residual risk**: a template rollout across many repos needs a migration script and an inventory page in the aggregate wiki listing which repos are onboarded and at which schema version.

### P17 — Bootstrap quality on big legacy repositories

- **Symptom**: the first run produces shallow, partly wrong pages; timeouts; runaway cost. "Cognition imposes generation-size limits. Very large monorepos may need `.devin/wiki.json` tuning" [S5]; generated docs show "limited navigation ability" [S43]; "the naive version … produced exactly the slop people are describing" until sources were split (vbarsoum) [S2]; DeepWiki misreads "heavy metaprogramming, code generation and unusual architectures" [S5].
- **Root cause**: one-shot generation over more code than fits in context; no dependency-aware ordering; the model guesses architecture from file names [S2].
- **Affects**: GEN, CI (bootstrap job), IDE (manual bootstrap).
- **Fixes**:
  - Resumable, page-by-page jobs: OpenWiki's "resumable page-job architecture" with `.run.json` checkpoints; "can still publish partial progress when a run fails after some pages complete" [S40][S41].
  - Dependency-aware order: DocAgent "determine[s] a dependency-aware processing order" [S43]; bootstrap leaf modules first, then composites (inferred from [S43]).
  - Start with a human-written skeleton: architecture overview, module ownership, and the 10 most important flows written by developers; the agent fills leaves. Human docs "remained competitive" in SWD-Bench [S43].
  - Exclude generated/vendored code and limit page count per run; smaller source units improve output [S2][S5].
  - Full regeneration once, then diff-based refresh (AutoWiki: "The first run analyzes the entire codebase; subsequent runs diff") [S42].
  - Mark bootstrap pages `confidence: unreviewed` and burn them down through review (draft→promote, P02) [S3].
- **Residual risk**: the bootstrap is the single most expensive and least accurate run; budget and staff it as a project, not a hook.

### P18 — Developers (and agents) bypass hooks

- **Symptom**: `git commit --no-verify`; hooks not installed on new clones; agents themselves bypass. "if pre-commit hooks take more than five seconds, they will be bypassed" [S24]; Claude Code used "`--no-verify`, `git stash`, and quiet flags" across 6 commits, landing "63 tests failed per commit", and the issue was closed "not planned" [S26][S25].
- **Root cause**: client-side hooks are advisory; `.git/hooks` is untracked ("every developer has to set it up manually" [S24]).
- **Affects**: LH (fundamental); IDE.
- **Fixes**:
  - "CI as the backstop": re-run the same check server-side; the MR cannot merge without it [S25][S24]. GitLab push rules and server hooks provide "server-side controls and enforcement" [S21].
  - For agents: PreToolUse hook (`block-no-verify`) or PATH shim on `git`; Claude Code deny rules "do not work as intended" because of prefix matching [S25].
  - Distribute hooks via `pre-commit`/Husky config in the repo [S24]; treat hook installation as part of repo onboarding (P16).
  - Design so bypass is harmless: the hook is a convenience trigger; the CI job is the source of truth (D02).
- **Residual risk**: a bypassed local hook simply delays the wiki update to CI; make sure nothing correctness-critical depends on the local hook.

### P19 — Non-determinism between runs (noisy diffs, churn)

- **Symptom**: re-running the agent on unchanged code rewrites paragraphs; MRs full of cosmetic changes; reviewers stop reading; indexes reorder.
- **Root cause**: sampling, floating-point non-associativity, batching, and model updates: "(a+b)+c can differ from a+(b+c)"; PyTorch uses "non-deterministic algorithms by default" [S45]; Copilot's "default [model] can change over time" and "there is still natural variation in generated text, even with pinned models" [S29].
- **Affects**: ALL; GEN and CI worst (frequent full runs).
- **Fixes**:
  - No-op detection before any model call: "A clean update skips model work" [S40]; only touch pages whose cited sources changed [S42].
  - Pin the model (`--model=`) [S29]; keep prompts and schema versioned so a change in output can be attributed.
  - Aim for "logically identical, not byte-identical" rebuilds (WUPHF) [S3]: canonicalise formatting (Prettier for Markdown, sorted index, stable IDs) after generation so cosmetic variation is normalised away (inferred).
  - Structured outputs (frontmatter JSON schema) validated on write; retry on validation failure [S45].
  - Minimum-diff prompt: instruct the agent to edit sections, not rewrite pages; CI rejects wiki MRs whose changed-line ratio is high for pages whose sources did not change (inferred).
- **Residual risk**: determinism is "nearly impossible" [S45]; design review around semantic diffs, not textual ones.

### P20 — Licence and data-residency concerns with Copilot

- **Symptom**: uncertainty whether a bot account may hold a Copilot seat; whether CLI use in GitLab CI is licensed; where prompts are processed.
- **Facts verified**:
  - "Seats are assigned to specific user accounts" [S36]; "If you receive Copilot from an organization, the Copilot CLI policy must be enabled in the organization's settings" [S30].
  - In GitHub Actions, Copilot CLI can run with a PAT ("AI credits are drawn from that user's Copilot seat") or with `GITHUB_TOKEN` ("authenticates as an installation, with no individual user associated"; "the recommended approach for automations") [S31]. **In GitLab CI there is no `GITHUB_TOKEN`**, so a PAT of a seat-holding account is the only path; fine-grained PATs "with the Copilot Requests account permission" work, "classic `ghp_` PATs are not supported" [S29]. OpenWiki's Copilot provider also rejects PATs and needs an OAuth token from `gh` login [S40].
  - Data residency: "GitHub Copilot now supports data residency for US and EU regions" (EU Data Boundary incl. EFTA from May 1 2026); admins must opt in; "+10%" credit cost; "Recently released models may take additional time to appear in data-resident regions" [S35]. The docs page is under Enterprise Cloud with data residency (GHE.com) — check whether it applies to the company's plan ❓.
  - Business vs Enterprise: content exclusion and org instructions need Business or Enterprise [S38][S39]; data-residency is documented for Enterprise Cloud with data residency [S35] ❓ for Business.
- **Unverified (❓)**: the GitHub Copilot Product Specific Terms (governing Business/Enterprise [S50]) could not be fetched during this task; from memory, GitHub's Terms of Service allow one "machine user" account per person for automation and prohibit sharing login credentials [S51]. Whether a machine user may hold a Copilot Business seat and drive Copilot CLI headlessly from GitLab CI **must be confirmed in writing with GitHub/the reseller** before choosing CI/WH models that depend on it.
- **Affects**: CI, WH (bot seat); GEN if hosted (SaaS data handling); LH/IDE use the developer's own seat (licence-clean, but the developer's credits pay).
- **Fixes**:
  - Prefer models where the developer's own seat does the work (IDE, LH triggering IDE agent) until the bot-seat question is settled (inferred).
  - If a bot seat is approved: dedicated named account, own cost centre and budget [S32], data-residency policy enforced [S35], CLI policy enabled [S30], `--secret-env-vars` and least-privilege tools [S29].
  - GitLab Duo CLI is the vendor-native alternative with "headless mode … built to run inside CI/CD pipelines" [S46] but is outside R6 unless licensed.
- **Residual risk**: licence terms and billing models changed twice in 2025-2026 (premium requests → AI credits, June 2026 [S32][S34]); re-verify quarterly.

### P21 — Over-privileged agent in the pipeline

- **Symptom**: a wiki job that can push to any branch, read all CI variables and reach the internet turns any P09 injection into RCE/exfiltration. Copilot CLI with `--allow-all-tools` "has the same access as you do … and can run any shell commands" [S30]; `--allow-all`/`--yolo` should be avoided "on privileged runners with deployment credentials" [S29].
- **Root cause**: convenience flags; shared runners with deploy secrets; broad project tokens.
- **Affects**: CI, WH, LH (developer machine credentials).
- **Fixes**: dedicated runner without deploy secrets; project access token scoped to `write_repository` on wiki paths only (enforce via push rules/CODEOWNERS on `wiki/`); `--deny-tool` for `git push`, `rm`, network tools; local sandboxing (`/sandbox enable`) or cloud sandboxes [S30]; branch protection so the bot can only open MRs [S18] (transfer of GitHub's mitigations).
- **Residual risk**: sandboxing features are "in public preview and subject to change" [S30].

### P22 — Lossy compounding: the wiki feeds on itself

- **Symptom**: pages get longer and vaguer with each pass; second-order facts replace first-order ones. "the compounding will just be rewriting valid information with less terse information" (devnullbrain) [S2]; "accumulate subtle errors as we start to regurgitate 2nd-order information" (Imanari) [S2]; "The few scientific studies out there actually show a degradation of output quality when these markdown collections are fully LLM maintained" (stingraycharles, citing [S8]) [S3]; "bad entries get cited by other agents" (ryanshrott) [S3].
- **Root cause**: the agent reads the wiki as input for the next rewrite instead of re-deriving from code; no provenance separating source-derived from wiki-derived claims.
- **Affects**: ALL; worst for schedule-driven full rewrites (GEN, CI lint passes).
- **Fixes**: every claim cites code, not another wiki page (OpenWiki claims sidecars [S40]); rewrite rule "re-derive from `raw/`/code, never summarise a summary" in the schema [S2 hombre_fatal]; length budget per page enforced by lint; lint passes propose changes as MRs rather than applying them (anuramat: "cron job … creates a PR if there's some easy win") [S3]; keep human-curated pages as anchors (P04).
- **Residual risk**: detection requires reading; sample-audit a few pages per month against code.

### P23 — Cross-repo knowledge (contracts, events, ownership) stays undiscoverable

- **Symptom**: each repo's wiki knows its own API but not who consumes it; agents cannot answer "who emits this event"; flat Markdown "doesn't query well and gets inconsistent" for structured things (mpazik) [S2]. WUPHF admits "no cross-office federation" [S3].
- **Root cause**: per-repo generation; no shared identifiers for contracts; aggregation (R8) is a static site, not a queryable index.
- **Affects**: ALL (design gap rather than execution-model failure).
- **Fixes (inferred unless noted)**: shared frontmatter vocabulary (`provides: [api:orders.v2]`, `consumes: [event:order.created]`) validated by the shared schema (P11); a nightly aggregate job that builds a cross-repo index from frontmatter only (deterministic, no LLM) and publishes it to the Quartz site; contract pages generated from OpenAPI/AsyncAPI files, not prose [S2 mpazik]; ownership from `CODEOWNERS`.
- **Residual risk**: vocabulary drift across teams; needs one owner for the shared schema.

### P24 — Write-only wiki: nobody reads it and the maintenance burden returns

- **Symptom**: the wiki is technically fresh but unused; the human cost moves from writing to babysitting. "Everyone is writing. Nobody is reading" (simsla) [S3]; "people using AI to do an immense amount of busywork and then never look at it again" (mplappert) [S3]; Newton: it "needs more or less constant maintenance … An error in the code means that one process or another stops running", and "too clunky for me to confidently recommend" [S44]; "Most of the value of writing docs is not in the final artifacts" (loveparade) [S2].
- **Root cause**: no consumer pull; the wiki is not on the path of any workflow (planning, review, incident).
- **Affects**: ALL.
- **Fixes**: make consumption mandatory in workflows — MR template links the pages that must be updated; review checklist "wiki updated?"; coding-agent prompts read the wiki first (P12); PO planning form reads from PO pages (R5) (inferred); measure reads (P15); keep the human-curated core small enough that people read it (P03).
- **Residual risk**: cultural; no tool fixes it.

## 3. Summary table

Severity: H = wrong decisions/security/licence exposure; M = quality or cost degradation; L = annoyance. Likelihood is for a hook/CI-driven multi-repo rollout with Copilot.

| ID | Problem | Sev | Likelihood | Affects | Best fix |
|----|---------|-----|-----------|---------|----------|
| P01 | Drift / staleness | H | Very high | ALL | Diff-driven refresh keyed on `source_commit` + whole-wiki lint [S42][S40][S1] |
| P02 | Hallucinated / over-confident pages | H | High | ALL (GEN worst) | Citations to code + draft→promote review [S5][S3] |
| P03 | Index/log bloat, context blow-up | M | Very high | ALL | Size budgets enforced by CI; tiered index + search [S6][S7][S1] |
| P04 | Agent destroys human edits | H | High | GEN, CI, WH | Ownership frontmatter + managed blocks + MR gate [S40][S18] |
| P05 | Merge conflicts on index files | M | High (LH) | LH, CI-on-branches | Generate `index.md` from frontmatter; single writer on `main` [S3][S41] |
| P06 | Agent commit re-triggers agent | H | High | CI, WH | Push with `CI_JOB_TOKEN` (no pipeline) + bot-exclusion rule [S20][S22] |
| P07 | Latency in commit path | M | Very high (LH) | LH, IDE | Hook only enqueues; agent runs async in CI [S24] |
| P08 | Cost / quota exhaustion | M | High | CI, WH, GEN | Budget per cost centre + no-op skip + path filters [S32][S40] |
| P09 | Prompt injection | H | Medium | ALL (CI/WH worst) | Do not feed free text; strip hidden chars; no egress; MR gate [S18][S12][S14] |
| P10 | Secrets in docs | H | Medium | ALL | Secret scan on wiki paths as required job; no secrets on runner [S28][S27] |
| P11 | Inconsistent structure across repos | M | High | ALL | Versioned schema via `include:project` + frontmatter lint [S48][S2] |
| P12 | Agents ignore the wiki | H | High | ALL | Instruction-style pointer in AGENTS.md; task-shaped pages; search tool [S8][S40] |
| P13 | Duplicated knowledge | M | High | ALL | One source, symlinked/imported pointers; dedupe lint [S11][S7] |
| P14 | PO content too technical | M | High | ALL | Audience tracks + human-owned PO pages + feedback form (inferred) |
| P15 | No evaluation | M | Very high | ALL | Task-based QA set + structural lint + rule probes [S43][S7] |
| P16 | Onboarding new repos | L | High | LH, CI, WH | CI component + `--init` style bootstrap [S48][S41] |
| P17 | Bootstrap quality on legacy repos | H | High | GEN, CI | Resumable page jobs, human skeleton, exclusions, `unreviewed` flag [S40][S43][S5] |
| P18 | Hook bypass | M | Very high | LH, IDE | CI as source of truth; hooks are convenience only [S25][S24] |
| P19 | Non-determinism / churn | M | Very high | ALL | No-op detection, pinned model, canonical formatting, section edits [S40][S29] |
| P20 | Licence / data residency | H | Medium ❓ | CI, WH | Confirm bot-seat terms in writing; EU residency policy; own cost centre [S31][S35] |
| P21 | Over-privileged agent | H | Medium | CI, WH, LH | Dedicated runner, scoped token, `--deny-tool`, MR-only [S30][S29] |
| P22 | Lossy compounding | M | High | ALL | Claims cite code only; re-derive, never summarise summaries [S40][S2] |
| P23 | Cross-repo knowledge gaps | M | High | ALL | Shared frontmatter vocabulary + deterministic aggregate index (inferred) |
| P24 | Write-only wiki | M | High | ALL | Put the wiki on the workflow path; measure reads (inferred) |

## 4. Design rules

Each rule is phrased as a checkable statement; problem IDs in brackets.

| # | Rule | Addresses |
|---|------|-----------|
| D01 | Every generated page carries frontmatter with `source_commit`, `sources: [paths]`, `owner: agent|human`, `audience`, `confidence`, `schema_version`; a CI lint rejects pages without it. | P01 P04 P11 P14 P22 |
| D02 | The local hook never calls the model. It may record intent or enqueue a job; the authoritative wiki update runs in CI or the webhook service and must complete in the background. | P07 P18 P05 |
| D03 | Local hooks are convenience only: every wiki check that matters is re-run as a required CI job on the MR, and bypassing the hook changes nothing about what can merge. | P18 P04 |
| D04 | The wiki bot pushes with `CI_JOB_TOKEN` (or a job that is excluded by `workflow: rules` on `$GITLAB_USER_LOGIN`), and the wiki job has `rules: changes:` excluding wiki paths, so a wiki commit can never start another wiki run. | P06 |
| D05 | The bot never commits to the default branch directly; it opens an MR that a human (or, for docs-only diffs under a size threshold, an allow-listed auto-merge rule) approves. | P04 P09 P21 P19 |
| D06 | `index.md`, category indexes and the cross-repo index are generated deterministically from frontmatter by a script, never edited by the model. `log.md` is append-only with `merge=union`. | P05 P19 P03 P23 |
| D07 | Before any model call, the job computes the set of pages whose `sources` changed since `source_commit`; if empty, it exits without calling the model. | P08 P19 P01 |
| D08 | The model edits sections of affected pages only; a full-page rewrite requires an explicit lint/compaction task and produces its own MR. | P19 P22 P04 |
| D09 | Human-owned pages (`owner: human`) and files outside the wiki allow-list (CI config, hooks, instruction files, `.vscode`, `.gitlab-ci.yml`) are read-only for the bot; CI fails the MR if the bot's diff touches them. | P04 P09 P21 |
| D10 | Generated pointers in AGENTS.md / CLAUDE.md / copilot-instructions live inside delimited managed blocks; everything outside the block is human-owned. | P04 P13 P12 |
| D11 | Root instruction files stay under 200 lines and contain only non-discoverable operational rules plus a "read these wiki pages first" instruction; knowledge lives in the wiki, not in instruction files. | P03 P12 P13 |
| D12 | Every factual claim in an agent page cites a code path (or a contract file), never another wiki page; lint flags pages with zero code citations. | P02 P22 |
| D13 | Bootstrap and lint output lands as `confidence: unreviewed` drafts; promotion to `reviewed` requires a human approval recorded in the MR. Load-bearing pages (contracts, runbooks, PO summaries) are never auto-promoted. | P02 P17 P14 |
| D14 | The bot's prompt contains the diff and code only. Commit messages, MR/issue text and third-party/vendored content are excluded, or passed in a delimited untrusted block after stripping hidden Unicode, HTML comments and zero-width characters. | P09 |
| D15 | The wiki runner has no deploy secrets, no outbound network except the model endpoint, a token scoped to wiki paths, and `--deny-tool` for `git push`, `rm` and network tools; `--allow-all`/`--yolo` is forbidden in CI. | P21 P09 P10 |
| D16 | A secret-detection job runs on wiki paths and is a required check; `.env*`, key material, terraform state and secrets directories are on the bot's ignore list; the Pages site is access-controlled. | P10 |
| D17 | The bot seat (if any) is a named account with its own cost centre and monthly budget; runs are debounced to one per MR merge and one scheduled lint per day; bootstrap runs have a separate budget. | P08 P20 |
| D18 | The wiki schema, CI job, lint and Pages publish step come from one shared `include:project` component with a `schema_version`; a repo is "onboarded" only when the lint passes at the current version. | P11 P16 P23 |
| D19 | An evaluation set (≥30 repo questions with expected paths/answers per repo) runs monthly; a wiki change that lowers the score blocks the next schema change. Agent runtime/tokens with vs without the wiki pointer are logged. | P15 P12 P24 |
| D20 | PO-facing pages follow a separate template and style contract, are `owner: human` with agent-appended "since last release" sections only, and have a feedback form (R5) whose answers are filed back as pages. | P14 P24 |
| D21 | The model is pinned by name in the job; prompts and schema are versioned in the repo; a model or prompt change is a reviewed MR that re-runs the evaluation set. | P19 P15 |
| D22 | Licence and residency are verified in writing before any execution model that needs a bot Copilot seat is adopted; the EU data-residency policy is enforced org-wide; the check is repeated quarterly. | P20 |

## 5. Sources

Tags: [fetched] = page opened and read in this task; [snippet] = only a search-result excerpt was available; [memory] = from prior knowledge, not verified today.

| # | Title | Author / org | Date | URL | Tag |
|---|-------|--------------|------|-----|-----|
| S1 | llm-wiki (gist) | Andrej Karpathy | 2026-04-04 | https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f | [fetched] |
| S2 | LLM Wiki – example of an "idea file" (HN thread, 296 pts) | Hacker News commenters | 2026-04-04 | https://news.ycombinator.com/item?id=47640875 | [fetched] |
| S3 | Show HN: A Karpathy-style LLM wiki your agents maintain (WUPHF) | najmuzzaman et al. / nex-crm | 2026-04-25 | https://news.ycombinator.com/item?id=47899844 | [fetched] |
| S4 | karpathy-llm-wiki (README) | Astro-Han | 2026 (daily since April) | https://github.com/Astro-Han/karpathy-llm-wiki | [fetched] |
| S5 | DeepWiki Complete Guide (2026) | Codersera | 2026-05-23 | https://codersera.com/blog/deepwiki-complete-guide-2026/ | [fetched] |
| S6 | Stop Bloating Your CLAUDE.md: Progressive Disclosure | Alexander Opalic | 2026-01-18 | https://alexop.dev/posts/stop-bloating-your-claude-md-progressive-disclosure-ai-coding-tools/ | [fetched] |
| S7 | How to Audit a Bloated CLAUDE.md File in 7 Steps | Brandon Waselnuk / Unblocked | 2026-07-31 | https://getunblocked.com/blog/audit-fix-bloated-claude-md/ | [fetched] |
| S8 | Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents? (arXiv 2602.11988) | Gloaguen, Mündler, Müller, Raychev, Vechev (ETH Zurich) | 2026-02-12 (v2 2026-06-23) | https://arxiv.org/abs/2602.11988 | [fetched] |
| S9 | On the Impact of AGENTS.md Files on the Efficiency of AI Coding Agents (arXiv 2601.20404) | Lulla, Mohsenimofidi, Galster, Zhang, Baltes, Treude | 2026-01-28 (v2 2026-03-30) | https://arxiv.org/abs/2601.20404 | [fetched] |
| S10 | AGENTS.md (essay) | Addy Osmani | 2026-02 | https://addyosmani.com/blog/agents-md/ | [fetched] |
| S11 | CLAUDE.md and AGENTS.md: The Configuration Layer… | TianPan.co | 2026-02-25 | https://tianpan.co/blog/2026-02-25-claude-md-agents-md-ai-coding-agent-instruction-files | [fetched] |
| S12 | Remote Prompt Injection in GitLab Duo Leads to Source Code Theft | Legit Security | 2025-05 (disclosed 2025-02-12) | https://www.legitsecurity.com/blog/remote-prompt-injection-in-gitlab-duo | [fetched] |
| S13 | GitHub Copilot: Remote Code Execution via Prompt Injection (CVE-2025-53773) | Johann Rehberger / Embrace The Red | 2025-08 | https://embracethered.com/blog/posts/2025/github-copilot-remote-code-execution-via-prompt-injection/ | [fetched] |
| S14 | Safeguarding VS Code against prompt injections | Michael Stepankin / GitHub | 2025-08-25 | https://github.blog/security/vulnerability-research/safeguarding-vs-code-against-prompt-injections/ | [fetched] |
| S15 | Dissecting the GitHub Copilot Prompt Injection Leak (CamoLeak); "It's trivial to prompt-inject GitHub's AI Copilot Chat" | Quilr AI; Pivot to AI | 2025-10 | https://www.quilr.ai/blog-details/dissecting-the-github-copilot-prompt-injection ; https://pivot-to-ai.com/2025/10/14/its-trivial-to-prompt-inject-githubs-ai-copilot-chat/ | [snippet] |
| S16 | New Vulnerability in GitHub Copilot and Cursor: "Rules File Backdoor" | Pillar Security | 2025-03-18 | https://www.pillar.security/blog/new-vulnerability-in-github-copilot-and-cursor-how-hackers-can-weaponize-code-agents | [fetched] |
| S17 | XOXO: Stealthy Cross-Origin Context Poisoning Attacks against AI Coding Assistants (arXiv 2503.14281) | (authors not captured) | 2025-03 | https://arxiv.org/abs/2503.14281 | [fetched] |
| S18 | Risks and mitigations for Copilot cloud agent | GitHub Docs | 2026 (live) | https://docs.github.com/en/copilot/concepts/agents/cloud-agent/risks-and-mitigations | [fetched] |
| S19 | MR !190326: pipeline chain tracking for CI_JOB_TOKEN pushes (max depth 5) | GitLab | 2025 | https://gitlab.com/gitlab-org/gitlab/-/merge_requests/190326 | [fetched] |
| S20 | CI/CD job token (docs) | GitLab Docs | 2026 (live) | https://docs.gitlab.com/ci/jobs/ci_job_token/ | [fetched] |
| S21 | CI/CD pipelines: skip a pipeline; Git push options | GitLab Docs | 2026 (live) | https://docs.gitlab.com/ci/pipelines/ ; https://docs.gitlab.com/topics/git/commit/ | [fetched] |
| S22 | `workflow` keyword (docs) | GitLab Docs | 2026 (live) | https://docs.gitlab.com/ci/yaml/workflow/ | [fetched] |
| S23 | Skipping GitLab CI pipeline execution on commits; "[emergency] gitlab ci running on endless loop" | Joel Koussawo (Medium); GitLab issue #41419 | 2023-2025 | https://medium.com/@joelkoussawo/skipping-gitlab-ci-pipeline-execution-on-commits-35f930834ebb ; https://gitlab.com/gitlab-org/gitlab-ce/-/issues/41419 | [snippet] |
| S24 | Using AI in Git Hooks for Pre-Commit Checks | DeployHQ | 2025-2026 | https://www.deployhq.com/git/ai-git-hooks | [fetched] |
| S25 | How to stop AI agents from bypassing pre-commit hooks | pydevtools | 2026 | https://pydevtools.com/handbook/how-to/how-to-stop-ai-agents-from-bypassing-pre-commit-hooks/ | [fetched] |
| S26 | Issue #40117: Agent bypasses git pre-commit hooks using --no-verify, stash, and quiet flags despite explicit deny rules | anthropics/claude-code | 2026-03-28 (closed not_planned) | https://github.com/anthropics/claude-code/issues/40117 | [fetched] |
| S27 | The State of Secrets Sprawl 2026; "29 million leaked secrets in 2025" | GitGuardian; Help Net Security | 2026-03-17; 2026-04-14 | https://blog.gitguardian.com/the-state-of-secrets-sprawl-2026/ ; https://www.helpnetsecurity.com/2026/04/14/gitguardian-ai-agents-credentials-leak/ | [fetched] / [snippet] |
| S28 | AI Agents Don't Understand Secrets. That's Your Problem. | Gus (0x711) / DEV Community | 2026-03-01 | https://dev.to/0x711/ai-agents-dont-understand-secrets-thats-your-problem-43n4 | [fetched] |
| S29 | Running GitHub Copilot CLI in Scripts and CI/CD Pipelines (Headless Mode) | Dev Leader | 2026-07-27 | https://www.devleader.ca/2026/07/27/running-github-copilot-cli-in-scripts-and-cicd-pipelines-headless-mode | [fetched] |
| S30 | About GitHub Copilot CLI | GitHub Docs | 2026 (live) | https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-copilot-cli | [fetched] |
| S31 | About using Copilot CLI in GitHub Actions | GitHub Docs | 2026 (live) | https://docs.github.com/en/copilot/concepts/agents/copilot-cli/copilot-cli-in-github-actions | [fetched] |
| S32 | About billing for GitHub Copilot in organizations and enterprises (AI credits) | GitHub Docs | 2026 (live, post June 2026) | https://docs.github.com/en/copilot/concepts/billing/organizations-and-enterprises | [fetched] |
| S33 | Usage limits for GitHub Copilot | GitHub Docs | 2026 (live) | https://docs.github.com/en/copilot/concepts/usage-limits | [fetched] |
| S34 | Copilot requests (legacy premium-request billing) | GitHub Docs | 2026 (live) | https://docs.github.com/en/copilot/concepts/billing/copilot-requests | [fetched] |
| S35 | Data residency (US + EU) and FedRAMP-authorized models now available in Copilot | GitHub Changelog | 2026-04-13 (updated 2026-04-24) | https://github.blog/changelog/2026-04-13-copilot-data-residency-in-us-eu-and-fedramp-compliance-now-available/ | [fetched] |
| S36 | GitHub Copilot seat assignment | GitHub Docs | 2026 (live) | https://docs.github.com/en/copilot/reference/copilot-billing/seat-assignment | [fetched] |
| S37 | Adding repository custom instructions for GitHub Copilot | GitHub Docs | 2026 (live) | https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions | [fetched] |
| S38 | Adding organization custom instructions for GitHub Copilot | GitHub Docs | 2026 (live) | https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-organization-instructions | [fetched] |
| S39 | Content exclusion for GitHub Copilot | GitHub Docs | 2026 (live) | https://docs.github.com/en/copilot/concepts/context/content-exclusion | [fetched] |
| S40 | langchain-ai/openwiki (README) | LangChain | 2026-06/07 | https://github.com/langchain-ai/openwiki | [fetched] |
| S41 | OpenWiki docs: Overview; Automate updates | LangChain | 2026-07 | https://docs.langchain.com/oss/openwiki/overview ; https://docs.langchain.com/oss/openwiki/automate-updates | [fetched] |
| S42 | AutoWiki (announcement) and AutoWiki Refresh (docs) | Factory.ai | 2026-06-17 | https://factory.ai/news/wiki ; https://docs.factory.ai/cli/features/wiki/auto-refresh | [fetched] |
| S43 | Evaluating Repository-level Software Documentation via Question Answering and Feature-Driven Development (SWD-Bench, arXiv 2604.06793) | Wang, Hu, Gao, Gao, Peng | 2026-04-08 | https://arxiv.org/abs/2604.06793 | [fetched] |
| S44 | An LLM wiki changed how I work | Casey Newton / Platformer | 2026-08-18 | https://www.platformer.news/karpathy-llm-wiki-journalism-productivity/ | [fetched] |
| S45 | Why is deterministic output from LLMs nearly impossible? | Shuveb Hussain / Unstract | 2025 | https://unstract.com/blog/understanding-why-deterministic-output-from-llms-is-nearly-impossible/ | [fetched] |
| S46 | Beyond BYOK: Why governance matters for AI agents (Duo CLI headless) | Jessica Hurwitz / GitLab | 2026-05-18 | https://about.gitlab.com/blog/gitlab-duo-cli-governance/ | [fetched] |
| S47 | Webhooks (signing token / secret token) | GitLab Docs | 2026 (live) | https://docs.gitlab.com/user/project/integrations/webhooks/ | [fetched] |
| S48 | Use CI/CD configuration from other files (`include:project`) | GitLab Docs | 2026 (live) | https://docs.gitlab.com/ci/yaml/includes/ | [fetched] |
| S49 | Changelog entries (Git trailers generate CHANGELOG.md) | GitLab Docs | 2026 (live) | https://docs.gitlab.com/development/changelog/ | [fetched] (conflict motivation: [memory] ❓) |
| S50 | GitHub Copilot Product Specific Terms (governs Business/Enterprise per S-terms page) | GitHub | — | https://github.com/customer-terms/github-copilot-product-specific-terms (returned HTTP 500/404 during this task) | [memory] ❓ |
| S51 | GitHub Terms of Service: account requirements (one person per account; machine users) | GitHub | — | https://docs.github.com/en/site-policy/github-terms/github-terms-of-service | [memory] ❓ |
| S52 | GitLab Duo vulnerability enabled attackers to hijack AI responses with hidden prompts | The Hacker News | 2025-05 | https://thehackernews.com/2025/05/gitlab-duo-vulnerability-enabled.html | [snippet] |
| S53 | Thread on the agent-wiki ecosystem (DeepWiki, AutoWiki, OpenWiki) | Himanshu (X) | 2026 | https://x.com/himanshutwtxs/status/2079819558093783438 | [snippet] |
