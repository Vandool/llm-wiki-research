---
id: ADR-09
title: "Publishing and aggregation architecture: per-repo wiki folders aggregated into a central hub site built with Quartz on GitLab Pages"
status: candidate        # candidate | recommended | rejected | superseded (changed by decision, not by researcher)
date: 2026-09-02
researcher: researcher-adr-09
fit_score: 8        # overall fit against ../requirements.md, justified in section 12
confidence: medium   # how well the key claims are verified against fetched sources
requirement_ratings: {R1: "✅", R2: "✅", R3: "✅", R4: "🟡", R5: "🟡", R6: "✅", R7: "✅", R8: "✅"}   # same symbols as section 5
tags: [publishing, aggregation, multi-repo, quartz, quartz-v5, gitlab-pages, gitlab-ci, multi-project-pipelines, pipeline-triggers, pages-access-control, obsidian-markdown, wikilinks, no-llm-in-path]
---

# ADR-09: Publishing and aggregation architecture: per-repo wiki folders aggregated into a central hub site built with Quartz on GitLab Pages

<!--
Uniform template for all approach ADRs in llm-wiki/approaches/.
Keep ALL headings, in this order, with these numbers. Add sub-sections freely.
Target length: 250-600 lines. Prefer tables and short paragraphs.
Mark unverified claims with ❓ and say what would verify them.
Never invent product features, URLs, or paper titles; if a search finds nothing, say so.
-->

## 1. Summary

This ADR covers the *publishing* dimension (R3 + R8) end to end and deliberately says nothing about who writes the pages (ADR-01..08 and ADR-10 do). Every repository keeps its wiki as plain Obsidian-flavoured Markdown under `wiki/<repo-slug>/` next to the code; a central `wiki-hub` GitLab project fetches every registered repo's `wiki/` folder in CI, adds deterministically generated cross-repo pages (contracts, events, owners, repositories, stale-page report, `llms.txt`), builds one Quartz site (full-text search, graph view, backlinks, explorer) and publishes it to GitLab Pages behind Pages access control. Child repos trigger a hub rebuild through GitLab multi-project pipelines (`trigger:project`) or a pipeline trigger token; a nightly schedule is the backstop. Quartz is the static-site generator that Karpathy-style wikis are usually paired with (Obsidian as "IDE" [S56]); its current major is **v5.0.0** (tag 2026-03-14, MIT, 13.2k stars, YAML config + community plugin system, Node ≥ 22) and its official docs ship a GitLab Pages `.gitlab-ci.yml` [S1][S2][S23]. Verdict: a low-risk, all-tier, zero-LLM publishing layer that fits R7/R8 exactly and gives R3 its cross-repo discoverability; adopt it as the shared UI for whichever writer approach wins, after a one-day spike on Quartz 5 link resolution and build time.

## 2. Context

- R8 asks for a browsable site on GitLab Pages, "Quartz preferred, ideally aggregating all repositories"; R3 asks that cross-repo knowledge (contracts, APIs, events, ownership) be discoverable and that the design survive fully autonomous agents. Neither is solved by any single-repo writer ADR; sibling ADRs (ADR-07 §3.7, ADR-08 §3.7, ADR-10 §3.7) all *assume* a Quartz hub and mark its aggregation and link handling ❓ [S58]. This ADR is that missing piece and verifies the assumptions.
- ADR-08 cites "Quartz 5 documents a GitLab Pages `.gitlab-ci.yml` (`image: node:24`, `npx quartz build`, `artifacts: paths: [public]`)". Verified and expanded in §3.7 and §4: the recipe also caches `.npm/` and `.quartz/plugins/`, runs `npx quartz plugin install` before the build, and is gated on the upstream branch name `v5`, which a hub on `main` must change [S2].
- Background problems this ADR addresses directly: P11 (inconsistent structure across repos), P16 (onboarding new repos), P23 (cross-repo knowledge undiscoverable), P10 (secrets published), P14 (PO-facing content), P24 (write-only wiki: put the wiki where humans look) [S57]. Design rules applied: D06 (generate indexes deterministically), D16 (access-controlled site), D18 (one shared CI component), D20 (PO pages separate) [S57].
- Hard constraints: R6 barely applies because there is no LLM anywhere in the publishing path; R7 is central and every GitLab feature used below is quoted with its tier.

## 3. The approach

### 3.1 Origin and provenance

| Item | Fact | Source |
|---|---|---|
| Quartz | "a fast, batteries-included static-site generator that transforms Markdown content into fully functional websites"; by Jacky Zhao (`jackyzha0/quartz`), repo created 2021-07-18; MIT; 13,153 stars / 4,084 forks / 69 open issues on 2026-09-02; default branch `v5`; last push 2026-08-18 | [S1][S23] |
| Current major | **v5.0.0** — tag `v5.0.0` at commit `ab346fa` "feat(v5): add plugin system (#2295)", 2026-03-14, author Emile Bangma (saberzero1), who also authored the most recent commits (July–August 2026). Package `@jackyzha0/quartz` 5.0.0, `engines: node >=22, npm >=10.9.2`. The last GitHub *release object* is still v4.0.8 (2023-08-21); v5 is tagged but not published as a release | [S23] |
| v5 changes that matter here | Config moved from TypeScript (`quartz.config.ts`, `quartz.layout.ts`) to `quartz.config.yaml`; plugins are standalone packages in the `quartz-community` GitHub org (40+ official plugins, installed with `npx quartz plugin add/install`, pinned in `quartz.lock.json`); layout is a per-plugin `layout: {position, priority}` property; "All generated URLs are now lowercased and hyphenated (e.g. `My Notes/Hello World.md` → `/my-notes/hello-world`)"; incremental rebuilds in watch mode only; Bases and Canvas page types | [S5][S6][S7] |
| Plugin maturity | e.g. `@quartz-community/search` 0.1.0 on npm, published 2026-07-22, MIT, "full-text search with FlexSearch integration"; `quartz-community/marketplace` registry pushed 2026-09-02 | [S24] |
| Multi-repo precedent | The "multi-repo docs hub" pattern is native to Antora (playbook with git content sources) and Backstage TechDocs; for Quartz there is no built-in multi-root support (issues #2259 and #1994 ask for multiple sites/roots from one vault and were closed without such a feature), so aggregation is a CI step in this design | [S25][S52][S53] |
| GitLab side | GitLab Pages, Pages access control, multi-project pipelines, pipeline trigger tokens, CI/CD job token, CI/CD components and scheduled pipelines are all "Tier: Free, Premium, Ultimate; Offering: GitLab.com, Self-Managed, Dedicated". Premium-only pieces are optional: parallel deployments, `needs:project`, group access tokens on GitLab.com, group webhooks, pull mirroring | [S26][S27][S30][S32][S37][S41][S42][S45][S46] |

### 3.2 How it works (architecture)

```
 child repo A (orders-service)          child repo B (checkout-frontend)         ... N repos
 ┌───────────────────────────┐          ┌───────────────────────────┐
 │ src/ …                    │          │ src/ …                    │
 │ AGENTS.md → "read wiki/"  │          │ AGENTS.md                 │
 │ wiki/orders-service/      │          │ wiki/checkout-frontend/   │
 │   index.md  log.md        │          │   index.md  log.md        │
 │   api/  events/  product/ │          │   integrations/ product/  │
 │ .gitlab-ci.yml            │          │ .gitlab-ci.yml            │
 │   include: component      │          │   include: component      │
 │   wiki:lint  wiki:publish │          │   wiki:lint  wiki:publish │
 └──────────┬────────────────┘          └──────────┬────────────────┘
            │ trigger:project (or trigger token / webhook)   on main, when wiki/** changed
            ▼                                       ▼
 ┌────────────────────────────────────────────────────────────────────────────────┐
 │ wiki-hub project (fork of Quartz v5)                                          │
 │  repos.yaml ─► aggregate job: sparse-clone wiki/ of each repo (CI_JOB_TOKEN)  │
 │              ─► tools/hub_index.py: contracts/, events/, owners, repositories,│
 │                 stale report, llms.txt   (deterministic, no LLM)              │
 │  hub-content/ (human-owned landing pages) ─► content/                         │
 │  build job: npm ci → npx quartz plugin install → npx quartz build -d content  │
 │  pages job: pages: {publish: public}  → GitLab Pages (access control)         │
 │  schedule: nightly full rebuild (backstop)                                     │
 └────────────────────────────────────────────────────────────────────────────────┘
            │                                                   │
            ▼                                                   ▼
   humans/PO: https://<hub-pages-url>/  (search, graph, backlinks)   agents: raw wiki/ in each repo,
   SSO-gated; "Only project members"                                 optional `snapshot` branch of the hub
```

- **Where the LLM runs:** nowhere in this ADR. Writer ADRs run it; this pipeline only copies, indexes and renders files.
- **Who authenticates:** the hub's `aggregate` job uses its own `CI_JOB_TOKEN` to read child repos ("Use `gitlab-ci-token` as the user, and the value of the job token as the password"); each child project adds the hub project (or the whole group) to its **job token allowlist**, and "the user that triggers the job must be a member of your project" [S37]. The pipeline's "user" is whoever pushed/ran/scheduled it, so schedules and trigger tokens should be owned by a service account that is a member of the top-level group. Alternative on self-managed (any licence) or GitLab.com Premium: a read-only group access token as a masked group variable [S46].
- **What triggers a run:** child pipeline on the default branch with changes under `wiki/**` (§3.4); nightly schedule; the "Run pipeline" form (§3.5); pushes to the hub itself (config, human-owned pages).
- **What is written and committed:** nothing, by default. `content/` and `public/` are build artefacts (`content/` is git-ignored in the hub), so the hub can never re-trigger itself or the children (P06 avoided by construction). Optional: the hub pushes an aggregated `content/` snapshot to a `snapshot` branch for agents that want one clone; that push must use the job token or `-o ci.skip` (D04) [S57].

### 3.3 Wiki content model it implies

This ADR only fixes what the *publishing layer* needs; page types and prose conventions come from the writer ADR.

| Element | Convention | Why |
|---|---|---|
| Location in each repo | `wiki/<repo-slug>/…` with `index.md` (catalogue) and `log.md` (append-only, Karpathy [S56]) at `wiki/<repo-slug>/`; sub-folders such as `architecture/`, `api/`, `events/`, `runbooks/`, `decisions/`, `product/` | The extra `<repo-slug>/` level makes hub-absolute wikilinks (below) resolve identically inside the repo (Obsidian/agents) and in the hub (`cp -r wiki/* content/`); a monorepo can contribute several slugs |
| File names | lowercase ASCII kebab-case, unique within the repo; folder `index.md` supplies the folder's display title in Explorer and listings ("Display names for folders get determined by the `title` frontmatter field in `folder/index.md`") [S15][S16] | Quartz 5 lowercases and hyphenates URLs [S5]; non-ASCII names broke link resolution (#2143) [S25] |
| Links | Obsidian wikilinks, **hub-absolute**: `[[orders-service/api/create-order]]`, `[[…\|Create order]]`, `[[…#request-body]]`, `[[orders-service/api/]]` for a folder listing; embeds `![[…]]`; markdown links `[x](/orders-service/api/create-order.md)` are equivalent. `markdownLinkResolution: absolute` ("Path relative to the root of the content folder") in the hub [S11][S14][S15] | `shortest` (Quartz's shipped default config) resolves by file name and would collide on `index`, `overview`, `runbook` across 20 repos [S4][S14]; matches OKF's "absolute links from bundle root" [S59] |
| Frontmatter Quartz reads | `title`, `description`, `permalink`, `aliases` (list), `tags` (list), `draft` (bool), `date` ("Normally uses `YYYY-MM-DD`") [S13]; Obsidian default properties `tags`, `aliases`, `cssclasses`; frontmatter must start at line 1 [S55] | Unknown keys are ignored, so D01's fields ride along |
| Frontmatter the hub reads (deterministic index, D01/D06) | `type` (service, endpoint, event, contract, runbook, decision, glossary, product-capability, team), `repo`, `audience: [dev, agent, po]`, `owner: human\|agent`, `source_commit`, `sources: [paths]`, `provides: [api:orders.v2]`, `consumes: [event:order.created]`, `status`/`stale_after` (OKF v0.2 names, ADR-07), `schema_version` | These generate the cross-repo pages that give the graph its cross-repo edges (P23) |
| Agent-facing vs human-facing | Agents read the repo's `wiki/<slug>/` (pointer in `AGENTS.md`, D10/D11); humans read the site; PO reads `product/` pages (`audience: [po]`) surfaced on the hub landing page (D20); the same files serve all three (R1) | No duplication (P13) |
| Hidden content | `draft: true` pages are dropped by the default `remove-draft` filter; `ignorePatterns` (`private`, `templates`, `.obsidian` by default) drop folders; **"all non-markdown files will be emitted and available publically in the final build"** [S4][S17] | Secret-scan `wiki/` in CI and keep the site access-controlled (P10, D16) |

### 3.4 Trigger and automation model

| Mechanism | How | Tier / constraints | Use |
|---|---|---|---|
| `trigger:project` in the child's pipeline | `trigger: {project: platform/wiki-hub, branch: main}` with `rules: [if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH, changes: [wiki/**/*]]`; variables are passed with `variables:` and `trigger:forward` [S26][S28] | All tiers. "The user triggering the upstream pipeline must have permission to start pipelines in the downstream project, otherwise the downstream pipeline fails to start" [S26] → keep the hub in the same top-level group so every developer inherits Developer role | **Primary** |
| Pipeline trigger token via `curl` | Hub Maintainer/Owner creates a token (Settings > CI/CD > Pipeline trigger tokens); child job `POST /projects/<hub_id>/trigger/pipeline` with `token`, `ref`, `variables[key]=value`; token stored as a masked **group** CI/CD variable [S27][S43] | All tiers; no membership requirement; `CI_PIPELINE_SOURCE == "trigger"` | Fallback when the hub lives outside the developers' group |
| `CI_JOB_TOKEN` to the trigger endpoint | `--form "token=$CI_JOB_TOKEN"`; shows up as a multi-project pipeline (`CI_PIPELINE_SOURCE == "pipeline"`) [S26][S27] | Hub must allowlist the child; user must be a member of the hub [S37] | Same membership issue as `trigger:project`; no advantage |
| Webhook straight to the trigger URL | Child project webhook, push events, branch filter = default branch, URL `…/api/v4/projects/<hub_id>/ref/main/trigger/pipeline?token=<token>`; payload available as `TRIGGER_PAYLOAD` [S27][S45] | Project webhooks all tiers; **group** webhooks Premium/Ultimate [S45]; fires on every push to main (no path filter) → the hub must skip when the repo's `wiki/` tree is unchanged | Zero-CI-change onboarding; noisier |
| Nightly schedule | Build > Pipeline schedules, cron, `CI_PIPELINE_SOURCE == "schedule"` [S41][S44] | All tiers; "cannot run more frequently than the instance's maximum scheduled pipeline frequency" [S41] | Backstop for missed triggers and for the stale report |
| Pull mirroring with "trigger pipelines for mirror updates" | Hub mirrors each child | Premium/Ultimate; syncs "30 minutes after a previous pull"; runs with the mirror owner's credentials [S40] | Not recommended: delay and credential smell |
| `needs:project` artefacts | Child publishes `wiki/` as a job artefact; hub fetches with `needs: [{project, job, ref, artifacts: true}]` | Premium/Ultimate and allowlist [S26] | Only if the child already runs a lint job whose *output* (rewritten links, generated pages) should be published instead of the raw folder |

Loop prevention and concurrency: the hub writes no commits, so no loops (P06). Bursts (five repos merging within a minute) are serialised with `resource_group: pages-publish` on the `pages` job [S28]; `interruptible: true` plus `workflow: auto_cancel: on_new_commit: interruptible` cancels redundant *commit* pipelines on the hub [S28], but whether GitLab treats repeated trigger pipelines on the same hub SHA as "redundant" is ❓ (spike Q3); worst case the extra runs cost minutes, not correctness. Merge conflicts cannot occur (nothing is merged).

### 3.5 Human retry / instruction channel ("the form")

For *publishing* the form is GitLab's own **Run pipeline** page on the hub: choose branch, add variables (e.g. `ONLY_REPO=orders-service`, `FULL_REBUILD=true`), run; schedules also accept "optional inputs, and CI/CD variables" [S41], and CI/CD components expose typed `spec:inputs` [S42]. That covers R5's "re-trigger" half for the site. Handing *instructions to an agent* (the other half of R5) is out of scope here and belongs to the writer ADR; the hub only adds a `product/feedback.md`-style page linking to that ADR's issue form. Non-technical editing of PO pages could use a Git-backed CMS in front of the hub (a practitioner pairs Quartz with Decap CMS "so that non technical users can edit documents" [S57 P14]) — optional, unverified for GitLab OAuth ❓.

### 3.6 Multi-repo / microservice fit

- **Per-repo vs central:** content stays per repo (ownership, MR review, agent locality); the hub is a *view*. Adding a repo = one line in `repos.yaml` + a 4-line `include: component` in the child + job-token allowlist entry (P16, D18).
- **Cross-repo links:** hub-absolute wikilinks work today because every repo's slug is unique and the hub content root is flat (`content/<slug>/…`). Quartz backlinks and popovers then work across repos with no extra tooling [S1].
- **Contracts, APIs, events, ownership (P23):** `tools/hub_index.py` reads frontmatter only and writes `content/platform/contracts/<id>.md` ("provided by [[orders-service/api/orders-v2]]; consumed by [[checkout-frontend/integrations/orders]]"), `events/<id>.md`, `owners.md` (from `owner`/`team` frontmatter, or CODEOWNERS), `repositories.md` (slug, title, `source_commit`, last update), `stale.md` (`stale_after` in the past or `source_commit` older than N days). Because these are real pages with wikilinks, the **global graph view shows service dependencies** and each service page gets backlinks from its consumers. ADR-08's deterministic backbone (OpenAPI/AsyncAPI-derived pages) plugs in unchanged.
- **Future autonomous agents (R3):** plain files, deterministic scripts, no prompts and no keys; an autonomous agent can read `content/` from the `snapshot` branch or fetch `llms.txt` and page HTML from the site with an access token in the `Authorization` header (Pages access control supports it [S30]).

### 3.7 Publishing / UI

**Quartz 5 on GitLab Pages — the official recipe, verified [S2].** `docs/hosting.md` ships this `.gitlab-ci.yml`: `image: node:24`; two caches (`npm-$CI_COMMIT_REF_SLUG` → `.npm/`, `plugins-$CI_COMMIT_REF_SLUG` → `.quartz/plugins/`); `build` job with `rules: - if: '$CI_COMMIT_REF_NAME == "v5"'`, `before_script: [hash -r, npm ci --cache .npm --prefer-offline]`, `script: [npx quartz plugin install, npx quartz build]`, `artifacts: paths: [public]`; a `pages` job with the same rule that only echoes and re-declares the `public` artefact. Notes: (1) the `v5` rule is the upstream branch name — change it to `$CI_DEFAULT_BRANCH`; (2) it relies on the legacy job name `pages`; the current keyword form is `pages: true` or `pages: {publish: public}` ("In GitLab 17.10+, this path is automatically appended to `artifacts:paths`") [S28][S29]; (3) the docs say "The page is private and only visible when logged in to a GitLab account with access to the repository" by default and can be made public in settings [S2]; (4) Node: image `node:24` while `engines` requires `>=22` [S1][S2]; (5) build time is **not documented** ❓ — troubleshooting only says "Slow builds: increase concurrency with `npx quartz build --concurrency 8`" [S21] (spike Q2).

**Base URL.** `baseUrl` is "the deployed URL without protocol or slashes … For GitHub Pages subpaths, include the full path like `jackyzha0.github.io/quartz`" [S3]; the CLI also has `--baseDir` [S8]. GitLab project Pages are served under a subpath (`https://<group>.gitlab.io/wiki-hub/`, subgroups `…/subgroup/wiki-hub/`) unless (a) the default **unique domain** is kept (`https://wiki-hub-<6 chars>.gitlab.io/`, "By default, every new project uses Pages unique domains"), (b) the project is the group's root Pages project (`https://<group>.gitlab.io/`), or (c) a custom domain is used [S29][S34]. Recommendation: **avoid a subpath** (unique domain or custom domain) because subpath link bugs have bitten Quartz before (#1013, folder/home links omitted the base subdirectory; closed 2024-07-10) [S25]. GitLab Pages serves `index.html` for directory URLs and appends `.html` for extension-less URLs [S35], so Quartz's `file.html` output style (flagged as a GitHub Pages caveat in the Quartz docs [S2]) is fine on GitLab.

**Search, graph, backlinks.** Search "is powered by Flexsearch", indexes "title, content and tags, weighing title matches above content matches", strips Markdown, and claims "search results in under 10ms for Quartzs as large as half a million words"; `ctrl+K`, tag search with `#` [S9]. Graph view: local graph ("at most one hop away") and global graph ("all the notes"), options `depth`, `repelForce`, `showTags`, `focusOnHover`, `enableRadial` [S10]. Backlinks, Explorer (folder tree; `folderDefaultState`, filter/sort/map), folder and tag listing pages (`[[folder/]]`, `/tags`), breadcrumbs, table of contents, recent notes, popover previews, Mermaid (part of Obsidian compatibility; "reorder your plugins so that ObsidianFlavoredMarkdown is after SyntaxHighlighting" if diagrams do not show), callouts, LaTeX, Bases ("database-like views … tables, cards, galleries") [S1][S12][S15][S16][S18][S19].

**Access control.** Pages access control: "Tier: Free, Premium, Ultimate"; visibility for private projects "Only project members" or "Everyone"; internal projects add "Everyone with access"; with SAML SSO "users must authenticate using SSO"; programmatic access by "the `Authorization` header with an access token"; group owners can "remove the public visibility option for Pages" for all projects in the group [S30]. Self-managed: the administrator must set `gitlab_pages['access_control'] = true` first, and can "Disable public access to Pages sites" instance-wide [S31]. Size: GitLab.com "Maximum site size: 1 GB"; self-managed default 100 MB, configurable [S31][S33].

**Per-repo Pages sites vs one hub.** One hub gives cross-repo search/graph/backlinks and one URL; per-repo sites duplicate the Quartz build in every repo and lose cross-repo edges. Middle ground: the hub, plus Premium/Ultimate **parallel deployments** (`pages: {path_prefix: "$CI_COMMIT_BRANCH", expire_in: 1 week}`, GA 17.9, default expiry 24 h, URL `https://<unique-domain>/<prefix>` or `https://namespace.gitlab.io/project/<prefix>`, 100/500 extra deployments on GitLab.com Premium/Ultimate) for MR previews of the hub itself [S32][S33]. Note the path-clash caveat: a `path_prefix` equal to an existing folder "overrides the existing path" [S32] — never use a repo slug as a prefix.

**Alternatives compared (all fetched 2026-09-02).**

| Tool | Multi-repo aggregation | Obsidian Markdown / wikilinks | Search | Graph / backlinks | GitLab Pages fit | Maintenance / maturity | Verdict for us |
|---|---|---|---|---|---|---|---|
| **Quartz 5** [S1]–[S24] | Not built in; one content root (#2259, #1994) → CI copy step (this ADR) | Native (ObsidianFlavoredMarkdown, callouts, embeds, tags, Mermaid, Bases) | FlexSearch, client-side | Yes, both | Official `.gitlab-ci.yml`; all tiers | MIT; v5 six months old, plugins at 0.1.x; active (Aug 2026 commits) | **Chosen**; R8 says "Quartz preferred" |
| MkDocs + Material [S49][S50][S51] | `mkdocs-monorepo-plugin` (Backstage, Apache-2.0, 399★) merges sub-`mkdocs.yml` via `!include`, multi-repo only "Using Git Submodules"; `mkdocs-multirepo-plugin` (MIT, 195★) pulls repos with `GitlabCIJobToken` but is "Project Status: Inactive"; Material's `projects` plugin is deprecated ("impossible to maintain") | No wikilinks or graph natively (needs extra plugins ❓); frontmatter tolerated | Built-in browser search | No graph; no backlinks | Trivial on Pages | Very mature (MIT); Python toolchain | Solid fallback if the team is Python-first and does not want graph/backlinks |
| Docusaurus 3.10 [S54] | `plugin-content-docs` multi-instance (one instance per repo, each with own sidebar/versioning) — content still has to be copied in; "If each documentation instance is very large, you should rather create 2 distinct Docusaurus sites" | MDX; no native wikilinks (community remark plugins ❓) | Algolia or local plugin | No | Fine on Pages | Meta, MIT, 66k★ | Over-featured for a wiki; MDX fights agent-written Markdown |
| GitLab built-in Wiki [S48] | Per-project git repo (`.wiki.git`); group wikis (Premium/Ultimate) span projects; cross-project links via `[wiki_page:namespace/project:Home]`; no aggregation/graph | `[[Home]]` wikilinks supported; Markdown/RDoc/AsciiDoc/Org | Title search in sidebar (advanced search on self-managed, see ADR-10) | No | Not Pages (own UI) | Vendor-maintained | Covered by ADR-10; loses graph/backlinks and the "one site" requirement |
| Backstage TechDocs [S53] | Native: each repo has `mkdocs.yml` + `docs/`, `backstage.io/techdocs-ref: dir:.`; "recommended" architecture: CI runs `techdocs-cli generate … publish --publisher-type awsS3\|googleGcs …` into object storage; GitLab supported | MkDocs Markdown; no wikilinks/graph | Backstage search | No | Not Pages: needs a running Backstage + object storage | Spotify/CNCF; heavy | Only if Backstage is already the developer portal |
| Antora 3.2 [S52] | Native multi-repo: playbook `content.sources: [{url, branches, start_path}]`, private repos via git credentials | **AsciiDoc only** ("you focus on authoring content in AsciiDoc") | Optional (Lunr extension ❓) | No | Runs anywhere; Node 24 recommended; MPL-2.0 | Mature, designed for this | Best-in-class aggregation but wrong markup for Obsidian-style agent output |

## 4. Concrete implementation sketch for our environment

Assumptions (from `requirements.md`): CI runners with outbound internet (npm + GitHub for plugins), a service account that is a member of the top-level group, Node available locally for previews. Everything below is tier-Free-compatible unless marked.

### 4.1 Hub repository layout (`platform/wiki-hub`, created from upstream Quartz `v5`)

```
wiki-hub/
├── quartz/                    # Quartz source (upstream v5; updated with `npx quartz upgrade`) [S7]
├── quartz.config.yaml         # §4.5
├── quartz.ts                  # optional TS overrides for callback options (Explorer sort/filter) [S3]
├── quartz.lock.json           # pinned plugin commits/versions [S7]
├── package.json / package-lock.json / .node-version
├── repos.yaml                 # registry of aggregated repositories (§4.2)
├── hub-content/               # HUMAN-OWNED hub pages, copied into content/ at build
│   ├── index.md               # landing page (PO first, then devs, then agents)
│   └── platform/index.md      # title "Platform (cross-repo)" for Explorer
├── tools/
│   ├── aggregate.sh           # sparse-clone wiki/ of each repo (§4.3)
│   ├── hub_index.py           # deterministic cross-repo pages + llms.txt (no LLM, D06)
│   └── wiki_lint.py           # shared frontmatter/link lint, also used by the child component
├── content/                   # BUILD OUTPUT of aggregate (git-ignored)
├── public/                    # BUILD OUTPUT of quartz (git-ignored)
└── .gitlab-ci.yml             # §4.3
```

### 4.2 Registry (`repos.yaml`)

```yaml
# one entry per repository; slug == wiki/<slug>/ folder name in that repo; lowercase kebab-case, unique
repos:
  - path: platform/orders-service        # GitLab project path
    slug: orders-service
    ref: main
  - path: frontend/checkout-web
    slug: checkout-frontend
    ref: main
```

### 4.3 Hub `.gitlab-ci.yml` (aggregate → build → pages)

```yaml
stages: [aggregate, build, deploy]

image: node:24                                     # Quartz recipe image [S2]

workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "pipeline"        # trigger:project from a child repo [S26]
    - if: $CI_PIPELINE_SOURCE == "trigger"         # trigger token or webhook [S27]
    - if: $CI_PIPELINE_SOURCE == "schedule"        # nightly backstop [S41]
    - if: $CI_PIPELINE_SOURCE == "web"             # "Run pipeline" form (R5)
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH  # hub's own changes
  auto_cancel:
    on_new_commit: interruptible                   # [S28]

variables:
  GIT_DEPTH: "1"
  WIKI_DIR: wiki                                   # folder inside each child repo
  ONLY_REPO: ""                                    # form variable: rebuild one repo only (optional) ❓ (script support)

cache:                                             # from the Quartz recipe [S2]
  - key: npm-$CI_COMMIT_REF_SLUG
    paths: [.npm/]
  - key: plugins-$CI_COMMIT_REF_SLUG
    paths: [.quartz/plugins/]

aggregate:
  stage: aggregate
  image: python:3.12-alpine
  interruptible: true
  before_script: [apk add --no-cache git, pip install --quiet pyyaml]
  script:
    - tools/aggregate.sh                           # writes content/<slug>/ for each repo
    - python tools/wiki_lint.py content --strict   # frontmatter + hub-absolute links (D01)
    - python tools/hub_index.py content            # platform/contracts, events, owners, repositories, stale, llms.txt
  artifacts:
    paths: [content/]
    expire_in: 1 day

build:
  stage: build
  interruptible: true
  needs: [aggregate]
  before_script:
    - hash -r
    - npm ci --cache .npm --prefer-offline         # [S2]
  script:
    - npx quartz plugin install                    # from quartz.lock.json [S2][S21]
    - npx quartz build -d content -o public        # -d = "directory to look for content files" (default content) [S8]
    - cp content/llms.txt public/llms.txt          # agent-facing index at the site root [S60]
  artifacts:
    paths: [public]
    expire_in: 1 week

pages:
  stage: deploy
  needs: [build]
  resource_group: pages-publish                    # serialise bursts [S28]
  script: [echo "Published to ${CI_PAGES_URL}"]    # CI_PAGES_URL [S44]
  pages:
    publish: public                                # [S28]
```

`tools/aggregate.sh` core (sparse clone with the job token; the archive API `GET /projects/:id/repository/archive?sha=<ref>&path=wiki` is the alternative [S38] — its archive root naming with `path=` is ❓, so the clone form is shown):

```bash
#!/usr/bin/env bash
set -euo pipefail
rm -rf content && mkdir -p content && cp -r hub-content/. content/
python3 - <<'PY' | while IFS=$'\t' read -r path slug ref; do
import yaml; [print(f"{r['path']}\t{r['slug']}\t{r.get('ref','main')}") for r in yaml.safe_load(open('repos.yaml'))['repos']]
PY
  [[ -n "${ONLY_REPO}" && "${ONLY_REPO}" != "${slug}" ]] && continue
  git clone --depth 1 --branch "${ref}" --filter=blob:none --sparse \
    "https://gitlab-ci-token:${CI_JOB_TOKEN}@${CI_SERVER_HOST}/${path}.git" "/tmp/${slug}"   # [S37]
  git -C "/tmp/${slug}" sparse-checkout set "${WIKI_DIR}"
  test -d "/tmp/${slug}/${WIKI_DIR}/${slug}" || { echo "missing ${WIKI_DIR}/${slug} in ${path}"; exit 1; }
  cp -r "/tmp/${slug}/${WIKI_DIR}/${slug}" "content/${slug}"
  echo "${slug} $(git -C "/tmp/${slug}" rev-parse HEAD)" >> content/.sources.txt         # for repositories.md
done
```

Prerequisite per child project: Settings > CI/CD > Job token permissions → add `platform/wiki-hub` (or the group) to the allowlist [S37]. Local preview: `PRIVATE-TOKEN` fallback in the script and `npx quartz build -d content --serve` [S8].

### 4.4 Child repo: shared component and the trigger job

Component project `platform/ci-components`, file `templates/wiki-publish.yml` (CI/CD components: all tiers; `include: component: $CI_SERVER_FQDN/platform/ci-components/wiki-publish@1.0.0` with `spec:inputs` [S42]):

```yaml
spec:
  inputs:
    hub_project: {default: platform/wiki-hub}
    hub_branch:  {default: main}
    wiki_dir:    {default: wiki}
    stage:       {default: deploy}
---
wiki:lint:
  stage: $[[ inputs.stage ]]
  image: python:3.12-alpine
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes: ["$[[ inputs.wiki_dir ]]/**/*"]
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      changes: ["$[[ inputs.wiki_dir ]]/**/*"]
  script:
    - pip install --quiet pyyaml
    # lint script fetched from the hub at a pinned ref (job token; hub must allowlist the child) ❓ or bake it into an image
    - wget --header "JOB-TOKEN: $CI_JOB_TOKEN" -O wiki_lint.py "$CI_API_V4_URL/projects/platform%2Fwiki-hub/repository/files/tools%2Fwiki_lint.py/raw?ref=main"   # [S37]
    - python wiki_lint.py "$[[ inputs.wiki_dir ]]" --strict --slug-from-path

wiki:publish-hub:                                # fire-and-forget multi-project trigger [S26]
  stage: $[[ inputs.stage ]]
  needs: [wiki:lint]
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      changes: ["$[[ inputs.wiki_dir ]]/**/*"]
  variables:
    SOURCE_PROJECT: $CI_PROJECT_PATH
    SOURCE_SHA: $CI_COMMIT_SHA
  trigger:
    project: $[[ inputs.hub_project ]]
    branch: $[[ inputs.hub_branch ]]
    # no strategy: child pipeline does not wait; `strategy: depend` is "not recommended" per docs [S26]
```

Child `.gitlab-ci.yml` addition (D18):

```yaml
include:
  - component: $CI_SERVER_FQDN/platform/ci-components/wiki-publish@1.0.0
    inputs: {stage: deploy}
```

Fallback trigger job when developers are not members of the hub (`WIKI_HUB_TRIGGER_TOKEN` and `WIKI_HUB_PROJECT_ID` as masked group variables [S27][S43]):

```yaml
wiki:publish-hub:
  image: curlimages/curl:latest                   # ❓ pin a tag
  rules: [{if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH, changes: ["wiki/**/*"]}]
  script:
    - curl --fail --request POST
        --form "token=${WIKI_HUB_TRIGGER_TOKEN}" --form "ref=main"
        --form "variables[SOURCE_PROJECT]=${CI_PROJECT_PATH}" --form "variables[SOURCE_SHA]=${CI_COMMIT_SHA}"
        "${CI_API_V4_URL}/projects/${WIKI_HUB_PROJECT_ID}/trigger/pipeline"      # [S27]
```

### 4.5 `quartz.config.yaml` essentials (v5 YAML; entries mirror the shipped default config [S4])

```yaml
configuration:
  pageTitle: Engineering Wiki
  pageTitleSuffix: " · ACME"
  enableSPA: true
  enablePopovers: true
  analytics: null                                  # no third-party analytics on an internal site
  locale: en-US
  baseUrl: wiki-hub-a1b2c3.gitlab.io               # unique domain / custom domain / <group>.gitlab.io — no subpath (§3.7) [S3][S29]
  ignorePatterns: [private, templates, .obsidian, "**/log.md"]   # drop log.md from the site if it drowns search (optional)
  theme: {fontOrigin: local, cdnCaching: false, typography: {header: Schibsted Grotesk, body: Source Sans Pro, code: IBM Plex Mono}}  # local fonts: no Google CDN calls from an internal site ❓ (verify fontOrigin: local packaging)
plugins:
  - source: "@quartz-community/obsidian-flavored-markdown"   # wikilinks, callouts, mermaid, tags [S12]
    enabled: true
    options: {enableCheckbox: true}
    order: 30
  - source: "@quartz-community/crawl-links"
    enabled: true
    options: {markdownLinkResolution: absolute, prettyLinks: true, disableBrokenWikilinks: false}   # hub-absolute links [S14]
    order: 60
  - source: "@quartz-community/remove-draft"                 # drop draft: true [S17]
    enabled: true
  - source: "@quartz-community/content-index"
    enabled: true
    options: {enableSiteMap: true, enableRSS: false}
  - source: "@quartz-community/search"                       # FlexSearch [S9][S24]
    enabled: true
    layout: {position: left, priority: 20, group: toolbar, groupOptions: {grow: true}}
  - source: "@quartz-community/explorer"
    enabled: true
    layout: {position: left, priority: 50}
    options: {folderDefaultState: collapsed}                 # 20+ repo folders [S16]
  - source: "@quartz-community/graph"
    enabled: true
    layout: {position: right, priority: 10}
    options: {globalGraph: {showTags: false, depth: -1}}     # option names per graph docs [S10]; YAML nesting ❓ verify against plugin README
  - source: "@quartz-community/backlinks"
    enabled: true
    layout: {position: right, priority: 50}
  - source: "@quartz-community/folder-page"
    enabled: true
  - source: "@quartz-community/tag-page"
    enabled: true
  # optional: "@quartz-community/bases-page" for PO tables over frontmatter (§4.7) [S19]
```

`quartz.lock.json` pins plugins; upgrade path is `npx quartz upgrade` + `npx quartz plugin install --latest` + `npx quartz plugin prune` in a reviewed MR [S7].

### 4.6 Link and frontmatter conventions (shipped as `wiki/README.md` template and enforced by `wiki_lint.py`)

```markdown
---
title: Create order (POST /orders)          # Quartz title [S13]
description: Validates the basket and emits order.created
type: endpoint                              # hub index (D01)
repo: orders-service
audience: [dev, agent]                      # po pages: [po]
owner: agent                                # human | agent (D09)
tags: [api, orders]
aliases: [create-order-endpoint]            # stable names across renames [S13]
provides: [api:orders.v2/create-order]
consumes: []
source_commit: 3f9c2d1
sources: [src/orders/api/create.py, openapi/orders.yaml]
status: stable                              # OKF v0.2 names (ADR-07)
stale_after: 2026-12-01
schema_version: 1
---
See [[orders-service/events/order-created]] and the consumer [[checkout-frontend/integrations/orders|checkout integration]].
Runbook: [[orders-service/runbooks/order-stuck#diagnosis]]. Folder: [[orders-service/api/]].
```

Rules: (1) links are hub-absolute `[[<slug>/<path>]]` — never bare names; (2) file and folder names lowercase ASCII kebab-case; (3) `index.md` in every folder with a `title`; (4) no non-Markdown files except images under `wiki/<slug>/assets/`; (5) `draft: true` for pages not ready to publish; (6) `permalink` only via lint-checked uniqueness. Agents get these rules as negative constraints in `AGENTS.md` (P16 finding "guardrails beat guidance" [landscape §7c]).

### 4.7 PO-facing landing page and sections

`hub-content/index.md` (human-owned, D20): (a) "What the platform does" in plain language with links to each repo's `product/overview` page; (b) "Changed recently for users" — generated section from `audience: [po]` pages sorted by `date` (hub_index writes `platform/recent-product-changes.md`; Quartz's recent-notes component is the alternative); (c) "For developers" → `platform/repositories`, `platform/contracts`, `platform/events`, `platform/owners`; (d) "For agents" → `llms.txt`, `platform/stale`. A Bases table (`.base` file rendered by `bases-page`) can list all `type: service` pages with owner and status columns — Obsidian Bases "view, edit, sort, and filter files and their properties" [S19][S55]; filter syntax in the Quartz port is ❓ (spike Q6).

### 4.8 Rollout steps

1. Create `platform/wiki-hub` from Quartz upstream `v5`; commit `repos.yaml`, `hub-content/`, `tools/`, `.gitlab-ci.yml`; set Pages visibility to "Only project members" (self-managed: admin enables access control first) [S30][S31]; group setting "remove public visibility option" [S30].
2. Publish the `wiki-publish` component (1.0.0) [S42]; create the trigger token and group variables [S27][S43].
3. Onboard two repos (backend + frontend): add `wiki/<slug>/index.md`, include the component, allowlist the hub [S37]; run the spike (§11).
4. Roll out to all repos with a migration script; nightly schedule; owners on `platform/owners`.

## 5. Requirements check

| ID | Requirement (short) | Rating | Evidence / notes |
|----|---------------------|--------|------------------|
| R1 | Dual audience (agents + devs + PO) | ✅ | Same Markdown serves agents (raw `wiki/<slug>/` in repo, `llms.txt`, snapshot branch), developers (search/graph/backlinks site) and the PO (`audience: [po]` pages, landing page §4.7). Quality of PO prose is the writer ADR's job (P14). |
| R2 | Context layer for whole AI dev pipeline | ✅ | Per-repo wiki plus deterministic cross-repo pages (contracts, events, owners, stale report) give planning/implementation/review/ops agents fixed entry points without reading the codebase (P12 pointer in `AGENTS.md`, D11). |
| R3 | Multi-repo microservices, future autonomous agents | ✅ | Core of the ADR: registry-driven aggregation, hub-absolute links, frontmatter-derived cross-repo graph (P23); no LLM, no keys, plain files → survives autonomous agents. Verified GitLab mechanisms on all tiers [S26][S27][S37]. |
| R4 | Bootstrap once, dev-owned upkeep, hook-triggered auto-update | 🟡 | This ADR provides the publish trigger (child pipeline → hub) and the shared component; bootstrap and content upkeep are out of scope (writer ADRs). Push-triggered publishing is automatic and verified. |
| R5 | Human retry / instructions via a form | 🟡 | Re-trigger: GitLab "Run pipeline" with variables/inputs on the hub [S41][S42]. Instruction hand-over to an agent is not part of the publishing layer. |
| R6 | Copilot-only (no API keys, no direct model access) | ✅ | Not applicable: no model call anywhere in the pipeline; only npm/GitHub egress for Quartz plugins. |
| R7 | GitLab, not GitHub | ✅ | GitLab Pages, Pages access control, multi-project pipelines, trigger tokens, job token allowlist, CI/CD components, schedules — all quoted with tiers; self-managed vs GitLab.com differences noted (access control enablement, group tokens, 1 GB vs 100 MB). |
| R8 | UI on GitLab Pages (Quartz) | ✅ | Quartz 5 documents the GitLab Pages pipeline [S2]; aggregation of all repos designed and mechanism-verified; residual ❓ on build time and one-content-root link behaviour (spike Q1/Q2). |

## 6. Pros

- **Zero LLM, zero keys, zero seats** in the publishing path; the pipeline is deterministic and reviewable (D06).
- **All GitLab tiers, SaaS and self-managed**: Pages, access control, multi-project pipelines, trigger tokens, job token, components, schedules are Free-tier features [S26][S27][S30][S37][S41][S42].
- **Quartz is the R8 preference and the de-facto companion of Obsidian-style LLM wikis**: wikilinks, callouts, Mermaid, tags, backlinks, graph, FlexSearch out of the box [S1][S9][S10][S12].
- **Cross-repo discoverability without a database**: generated contract/event pages turn frontmatter into graph edges and backlinks (P23).
- **Content stays with the code**: per-repo ownership, MR review, agent locality; the hub is disposable and rebuildable.
- **Onboarding is a 4-line include + one registry line** (P16, D18).
- **Containment**: access-controlled site plus secret scan on `wiki/` limits the blast radius of P10.
- **Cheap**: MIT everywhere; cost is CI minutes only (§10).

## 7. Cons and risks

- **Quartz 5 is young**: tagged 2026-03-14, plugins at 0.1.x (July 2026), no GitHub release object, config format and plugin sources changed in 2026 (`github:` → npm specifiers) [S5][S7][S23][S24]. Expect upgrade churn; pin with `quartz.lock.json`.
- **Single content root**: multi-repo needs the copy step and the `wiki/<slug>/` convention; deviations (a repo with `docs/` instead) need per-repo mapping in `repos.yaml`.
- **Link discipline is load-bearing**: `shortest` resolution silently picks the wrong page on name collisions; `absolute` requires agents to write `[[<slug>/…]]` consistently (lint enforced, but agent output is non-deterministic, P19).
- **Client-side search only**: FlexSearch runs in the browser; agents cannot use it — they need grep/`qmd` over files (Karpathy's suggestion [S56]).
- **Full rebuild per trigger**: Quartz incremental rebuilds exist only in watch mode [S6]; at hundreds of triggers a day the hub becomes a CI-minutes consumer (GitLab.com Free: 400 minutes/month [S47]).
- **Everything non-Markdown in `wiki/` is published** [S17] — images with secrets, exported configs.
- **Pages access control depends on instance configuration** on self-managed [S31]; if disabled, the site is public to the instance.
- **Trigger permission coupling**: `trigger:project` fails when the pushing developer lacks permission in the hub [S26]; mitigated by group placement or trigger token, but it is a recurring onboarding gotcha.
- **A hub is a second place to look**: without the `AGENTS.md` pointer and MR-template links, humans and agents keep ignoring it (P12, P24).

## 8. Known problems reported by practitioners, and fixes

| # | Problem (source) | Fix / mitigation |
|---|---|---|
| 1 | Quartz's GitLab CI example churned three times: 2023 request and PR (#433, #548, #549); 2024 PR #1243 replaced it because the previous version "relied on the default image being debian based" and fixed ".npm folder caching to work with modern versions on gitlab"; 2024 PR #1365 changed the runner tag because GitLab.com shared runners moved from `docker` to `gitlab-org-docker`; 2025 PR #2017 refreshed the instructions [S25] | Pin `image: node:24`, do not use runner tags at all (instance runners pick up untagged jobs), keep both caches; treat the upstream snippet as a starting point, not a contract |
| 2 | Subpath hosting: #1013 "Folder and home links not working … links … omitted the base-level subdirectory" (2024-03 → closed 2024-07) [S25] | Host without a subpath (unique domain, group root project or custom domain) and set `baseUrl` accordingly; keep one smoke test that clicks a folder and the home link on the deployed site |
| 3 | Same-named folders: #676 "Breadcrumb has wrong label when multiple folders exist with same name" (closed 2024-02-11) [S25] — with 20 repos each having `api/` and `runbooks/` this is the normal case | Verify on v5 in the spike (Q1); give every folder `index.md` with a distinct `title` ("Orders API", not "API") |
| 4 | Ambiguous shortest-path links (Quartz default config ships `markdownLinkResolution: shortest`; the CrawlLinks doc describes `shortest` as "Name of the file. If this isn't enough to identify the file, use the full absolute path") [S4][S14] | `absolute` + hub-absolute link rule + lint; `disableBrokenWikilinks: false` so broken links are visibly styled |
| 5 | Non-ASCII file names break resolution (#2143 umlauts) [S25] | ASCII kebab-case rule in lint |
| 6 | "All non-markdown files will be emitted and available publically" [S17] → secrets in exported configs/screenshots (P10) | Secret scanning on `wiki/` as a required MR job; lint allow-list of file types; access-controlled site (D16) |
| 7 | Plugin install failures on fresh clones / "ExternalPlugin.X is not a function"; resource exhaustion during plugin install on small runners [S21] | `npx quartz plugin install` from the lock file (never `--latest` in CI); cache `.quartz/plugins/`; `-c 1` on small runners |
| 8 | Slow builds [S21]; no documented build-time figures ❓ | `--concurrency`; measure in spike Q2; split the hub if it exceeds the job budget |
| 9 | Multi-project trigger fails: "The user triggering the upstream pipeline must have permission to start pipelines in the downstream project" [S26] | Hub inside the developers' top-level group, or the trigger-token fallback (§4.4) |
| 10 | Aggregation via `needs:project` or group tokens unexpectedly needs Premium on GitLab.com [S26][S46] | Job-token sparse clone (Free) as shown; keep Premium features optional |
| 11 | Pages site accidentally public | Group-level "remove public visibility option" [S30]; instance-level "Disable public access to Pages sites" on self-managed [S31] |
| 12 | Non-technical users cannot edit Markdown in git (P14) | Practitioner pairing of Quartz with Decap CMS [S57]; or route PO edits through the R5 form of the writer ADR |
| 13 | Practitioner reports specifically about Quartz aggregating many repositories: **none found** (search budget exhausted after the primary-source sweep; GitHub issue search returned only single-vault requests #2259/#1994) ❓ | Treat multi-repo Quartz as our own pattern and validate it in the spike |

## 9. Scaling considerations

- **Page count and index size.** FlexSearch: "under 10ms for Quartzs as large as half a million words" [S9] — roughly 2,000 pages of 250 words. Beyond that the client-side index (shipped to every browser) grows linearly ❓ (size not documented); mitigations: exclude `log.md` and raw logs via `ignorePatterns` [S17], split archival pages into a second hub, or accept tag/title search only. Measure at 2k and 10k synthetic pages (Q2).
- **Global graph.** Thousands of nodes make the global graph slow and unreadable ❓ (no documented limit); keep `showTags: false`, rely on local graphs and the generated contract pages, which are the useful cross-repo edges anyway [S10].
- **Build time and minutes.** Full rebuild per trigger; Quartz's incremental rebuild applies to watch mode only [S6]. With N repos × avg 100 pages, expect minutes, not seconds ❓. Debounce with `resource_group` [S28], batch through the nightly schedule for low-traffic repos, and use `ONLY_REPO` partial aggregation if needed. GitLab.com Free tier: 400 compute minutes/month [S47]; self-managed quota disabled by default [S47].
- **Site size.** GitLab.com 1 GB [S33]; self-managed default 100 MB, configurable [S31] — images are the usual cause; keep `assets/` small.
- **Many repos.** `aggregate.sh` clones sequentially; parallelise with `xargs -P` or split into parent-child pipelines; job-token allowlist can be granted at group level [S37].
- **Drift and staleness (P01).** The hub's `platform/stale.md` (from `stale_after`/`source_commit`) is a deterministic freshness report; the site shows `source_commit` per page so readers know what revision a page describes (P05 residual: "the wiki describes `main`") [S57].
- **Schema evolution (P11).** `schema_version` in frontmatter; lint fails old versions at the hub; `repos.yaml` doubles as the onboarding inventory (D18).
- **Alternative at very large scale.** Per-repo Quartz sites plus a hub of generated cross-repo pages that link *out* to them (loses unified search/graph) — or Antora if the organisation moves to AsciiDoc [S52].

## 10. Effort and cost estimate

| Item | Estimate | Notes |
|------|----------|-------|
| Bootstrap (one-off) | 3–5 person-days for hub repo, `aggregate.sh`, `hub_index.py`, `wiki_lint.py`, component, conventions doc, landing page; ~0.5 h per repo to onboard | No LLM cost. Assumes the writer ADR delivers the frontmatter fields |
| Per-commit / per-MR run | Child: lint job ≈ 30–60 s. Hub: aggregate 1–2 min for 20 repos + build (❓ 1–5 min, spike Q2) + pages ≈ 30 s → ≈ 3–8 min per trigger | At 20 triggers/day ≈ 60–160 min/day ≈ 2–5k compute minutes/month ❓ — above GitLab.com Free (400) [S47]; fine on own runners or paid tiers |
| Ongoing maintenance per week | 1–2 h: Quartz/plugin upgrades (quarterly MR), broken-link report triage, registry updates | Quartz 5 churn risk (§7) |
| Infrastructure | GitLab Pages (all tiers), one runner with outbound npm/GitHub access; optional Premium for parallel deployments / group tokens / group webhooks / `needs:project` | Self-managed: admin enables Pages access control [S31] |
| Licensing / seats | Quartz MIT, plugins MIT [S23][S24]; no LLM seats; no SaaS | R6 not touched |

## 11. Open questions and spike plan

| # | Question | Smallest experiment | Effort |
|---|---|---|---|
| Q1 | Do hub-absolute wikilinks, folder listings, breadcrumbs and Explorer behave correctly with two repos that both have `api/` and `runbooks/` folders under `content/<slug>/`, with `markdownLinkResolution: absolute`? Does `-d content` accept the aggregated tree? | Build the hub on GitLab.com Free with two toy repos (20 pages each), deploy to Pages with a unique domain, click through 20 links, check breadcrumbs (#676), Mermaid, popovers, search | 1 day |
| Q2 | Build time and search-index size at 2,000 and 10,000 pages | Generate synthetic pages; run `npx quartz build` with `--concurrency` 2/4/8 on a shared runner; record wall time and `public/` size | 0.5 day |
| Q3 | Trigger semantics: does `auto_cancel` collapse repeated trigger pipelines on the same hub SHA? Does `trigger:project` work for a Developer of the group? Minutes per burst of 5 triggers | Push wiki changes to both toy repos within a minute; observe pipelines | 0.5 day |
| Q4 | Job-token allowlist at group level on self-managed vs GitLab.com; archive-API root naming with `path=wiki` (if the archive route is preferred over sparse clone) | Try both in the toy setup | 0.5 day |
| Q5 | Pages access control with the company's SSO; can an agent fetch `llms.txt` with an `Authorization` header [S30]? | Configure "Only project members"; `curl -H "Authorization: Bearer <PAT>"` | 0.5 day |
| Q6 | Bases-page filter syntax for a PO table (`audience == po`, `type == service`) [S19] | One `.base` file in `hub-content/platform/` | 0.5 day |
| Q7 | Governance: who owns the hub fork and its quarterly `npx quartz upgrade`; is `fontOrigin: local` sufficient for an internal site with no CDN egress? | Decision + one upgrade rehearsal | 0.5 day |

## 12. Verdict

**Fit score 8/10.** For the dimension it covers (R3 discoverability + R8 UI) every mechanism is a documented, all-tier GitLab or Quartz feature; it introduces no LLM, no keys and no SaaS (R6 trivially satisfied, R7 fully). Points off for: Quartz 5's youth and plugin churn, the unverified build-time/link-behaviour details that only a spike can settle (confidence: medium), and the fact that it is a component, not a complete solution — R4 and R5 are only half-served by design.

**When to choose it:** whenever the writer approach produces Markdown files in the repository (ADR-01..08 all do). Do not choose it if the organisation standardises on AsciiDoc (use Antora [S52]) or already runs Backstage as the developer portal (use TechDocs [S53]); ADR-10's GitLab Wiki path is the only writer approach that would not need it, and even ADR-10 proposes this hub for the aggregated UI.

**Combines with:** ADR-08 (its deterministic backbone yields exactly the `provides`/`consumes` frontmatter the hub index needs, and its §3.7 assumed this pipeline); ADR-07 (OKF `type`/`status`/`stale_after` fields drive the stale report; its open question on bundle-relative link rewriting is answered here by the `wiki/<slug>/` + absolute-link convention); ADR-10 (same Pages pipeline, so switching the maintainer later is a content change, not a publishing change); the CI-side and hook-side execution ADRs (ADR-01/02) supply the `wiki/` commits that fire the trigger job.

## 13. Sources

1. [S1] "Quartz 5" documentation index — Jacky Zhao — live 2026-09-02 — https://quartz.jzhao.xyz/ — v5.0.0, Node ≥ 22 / npm ≥ 10.9.2, feature list (search, graph, backlinks, wikilinks, Obsidian compatibility, Bases, Canvas). [fetched]
2. [S2] "Hosting" — Quartz docs — https://quartz.jzhao.xyz/hosting and https://raw.githubusercontent.com/jackyzha0/quartz/v5/docs/hosting.md — GitLab Pages `.gitlab-ci.yml` (node:24, caches, plugin install, `v5` rule, private-by-default note), baseUrl requirement, `file.html` note. [fetched]
3. [S3] "Configuration" — Quartz docs — https://quartz.jzhao.xyz/configuration and https://raw.githubusercontent.com/jackyzha0/quartz/v5/docs/configuration.md — `quartz.config.yaml` structure, baseUrl subpath rule, ignorePatterns, plugin entry syntax, `npx quartz plugin add/install --from-config/prune`, `quartz.ts` overrides. [fetched]
4. [S4] `quartz.config.default.yaml` (branch v5) — https://raw.githubusercontent.com/jackyzha0/quartz/v5/quartz.config.default.yaml — verbatim configuration block and plugin entries (crawl-links `markdownLinkResolution: shortest`, search/graph/backlinks/explorer layout). [fetched]
5. [S5] "Migrating from Quartz 4" — https://raw.githubusercontent.com/jackyzha0/quartz/v5/docs/getting-started/migrating.md — TS→YAML, standalone plugins, layout removal, lowercased/hyphenated URLs, commands. [fetched]
6. [S6] "What's new" — https://raw.githubusercontent.com/jackyzha0/quartz/v5/docs/getting-started/whats-new.md — community plugin ecosystem, 40+ plugins, Bases/Canvas pages, incremental rebuilds in watch mode, Node < 22 check. [fetched]
7. [S7] "Upgrading" — https://raw.githubusercontent.com/jackyzha0/quartz/v5/docs/getting-started/upgrading.md — `npx quartz upgrade`, `quartz.lock.json`, `plugin install --latest`, `plugin prune`, npm `@quartz-community` specifiers. [fetched]
8. [S8] "Build" CLI reference and `quartz/cli/args.js` — https://quartz.jzhao.xyz/cli/build and https://raw.githubusercontent.com/jackyzha0/quartz/v5/quartz/cli/args.js — `-d` "directory to look for content files" (default `content`), `-o`, `--concurrency`, `--baseDir`. [fetched]
9. [S9] "Full-text search" — https://quartz.jzhao.xyz/features/full-text-search — FlexSearch, indexes, 10 ms / half a million words, shortcuts. [fetched]
10. [S10] "Graph view" — https://quartz.jzhao.xyz/features/graph-view — local/global graph and options. [fetched]
11. [S11] "Wikilinks" — https://quartz.jzhao.xyz/features/wikilinks — syntax variants, case-insensitive matching, lowercased URLs. [fetched]
12. [S12] "Obsidian compatibility" — https://quartz.jzhao.xyz/features/obsidian-compatibility — ObsidianFlavoredMarkdown scope (wikilinks, embeds, callouts, tags, Mermaid, frontmatter "same fields that Obsidian uses"). [fetched]
13. [S13] "Authoring content" — https://quartz.jzhao.xyz/getting-started/authoring-content — `content/`, `index.md`, frontmatter fields. [fetched]
14. [S14] "CrawlLinks" plugin — https://raw.githubusercontent.com/jackyzha0/quartz/v5/docs/plugins/CrawlLinks.md — `markdownLinkResolution` absolute/relative/shortest and other options. [fetched]
15. [S15] "Folder and tag listings" — https://quartz.jzhao.xyz/features/folder-and-tag-listings — folder index pages, `index.md` override, `[[folder/]]`, `/tags`. [fetched]
16. [S16] "Explorer" — https://quartz.jzhao.xyz/features/explorer — folder titles from `index.md`, `folderDefaultState`, filter/sort/map. [fetched]
17. [S17] "Private pages" — https://quartz.jzhao.xyz/features/private-pages — RemoveDrafts, ExplicitPublish, ignorePatterns, non-Markdown files emitted publicly. [fetched]
18. [S18] "Mermaid diagrams" — https://quartz.jzhao.xyz/features/mermaid-diagrams — enabled via Obsidian compatibility; plugin-order caveat. [fetched]
19. [S19] "Bases" — https://quartz.jzhao.xyz/features/bases — `.base` files as database-like views; `bases-page` plugin. [fetched]
20. [S20] "Layout" — https://quartz.jzhao.xyz/layout — layout defined in `quartz.config.yaml`, slots, `layout.position/priority`. [fetched]
21. [S21] "Troubleshooting" — https://raw.githubusercontent.com/jackyzha0/quartz/v5/docs/troubleshooting.md — slow builds/concurrency, plugin install issues, broken wikilinks. [fetched]
22. [S22] "Docker support" — https://quartz.jzhao.xyz/features/docker-support — local preview only, "Not to be used for production". [fetched]
23. [S23] GitHub API for `jackyzha0/quartz` — https://api.github.com/repos/jackyzha0/quartz (+ `/tags`, `/commits?sha=v5`, `/commits/ab346fa…`, `/releases`) and https://github.com/jackyzha0/quartz — 13,153★, 4,084 forks, MIT, default branch v5, pushed 2026-08-18; tag v5.0.0 = commit 2026-03-14 "feat(v5): add plugin system (#2295)"; last release object v4.0.8 (2023-08-21); `package.json` 5.0.0 with engines. [fetched]
24. [S24] `quartz-community` org repos (GitHub API) and npm registry `@quartz-community/search` — https://api.github.com/orgs/quartz-community/repos and https://registry.npmjs.org/@quartz-community/search — plugin repos (obsidian-flavored-markdown, content-index, bases-page, marketplace pushed 2026-09-02); search 0.1.0, MIT, 2026-07-22, "FlexSearch integration". [fetched]
25. [S25] Quartz issues/PRs via GitHub search API and issue endpoints — #2259, #1994 (multi-site/root requests), #676 (breadcrumb label with same-name folders), #1013 (folder links on subpath), #2143 (umlaut links), PR #1243 (2024-06-29, GitLab CI rework), PR #1365 (2024-08-21, `gitlab-org-docker` tag), #433/#548/#549 (2023 GitLab Pages support), PR #2017 (2025-06-17 GitLab Pages instructions) — https://github.com/jackyzha0/quartz/issues/676 , https://github.com/jackyzha0/quartz/issues/1013 , https://github.com/jackyzha0/quartz/pull/1243 , https://github.com/jackyzha0/quartz/pull/1365 . [fetched]
26. [S26] "Downstream pipelines" — GitLab Docs — https://docs.gitlab.com/ci/pipelines/downstream_pipelines/ — multi-project pipelines on all tiers, `trigger:project/branch/strategy/forward`, permission requirement, `CI_JOB_TOKEN` trigger curl, `needs:project` Premium + allowlist. [fetched]
27. [S27] "Trigger pipelines by using the API" (pipeline trigger tokens) — GitLab Docs — https://docs.gitlab.com/ci/triggers/ — token creation role, curl form, `variables[key]`, webhook trigger URL, `TRIGGER_PAYLOAD`, job-token behaviour. [fetched]
28. [S28] "CI/CD YAML syntax reference" — GitLab Docs — https://docs.gitlab.com/ci/yaml/ — `pages`, `pages:publish`, `path_prefix`, `expire_in`, `trigger`, `needs:project`, `include:project`, `rules:changes`, `resource_group`, `workflow:rules`, `interruptible` + `workflow:auto_cancel`. [fetched]
29. [S29] "GitLab Pages" — GitLab Docs — https://docs.gitlab.com/user/project/pages/ — `pages: true`, `public` folder, unique domains default, parallel deployments. [fetched]
30. [S30] "GitLab Pages access control" — https://docs.gitlab.com/user/project/pages/pages_access_control/ — tiers, visibility levels, SAML SSO, `Authorization` header, group-level removal of public option. [fetched]
31. [S31] "GitLab Pages administration" — https://docs.gitlab.com/administration/pages/ — `gitlab_pages['access_control'] = true`, disable public access, default max size 100 MB. [fetched]
32. [S32] "Parallel deployments" — https://docs.gitlab.com/user/project/pages/parallel_deployments/ — Premium/Ultimate, GA 17.9, `path_prefix` rules, URL forms, 24 h expiry, path clash. [fetched]
33. [S33] "GitLab.com settings" — https://docs.gitlab.com/user/gitlab_com/ — Pages 1 GB, `gitlab.io`, 150 custom domains, 100/500 extra deployments, rate limits. [fetched]
34. [S34] "Pages default domain names and URLs" — https://docs.gitlab.com/user/project/pages/getting_started_part_one/ — URL scheme for group/subgroup projects, unique domain, self-managed wildcard. [fetched]
35. [S35] "GitLab Pages introduction" — https://docs.gitlab.com/user/project/pages/introduction/ — `index.html` for directories, `.html` appended, 404 handling, `.br/.gz`. [fetched]
36. [S36] "Pages redirects" — https://docs.gitlab.com/user/project/pages/redirects/ — `_redirects`, 301/302/200, limits, all tiers. [fetched]
37. [S37] "CI/CD job token" — https://docs.gitlab.com/ci/jobs/ci_job_token/ — endpoints (files raw, archive, trigger), inbound allowlist, membership requirement, `gitlab-ci-token` clone. [fetched]
38. [S38] "Repositories API" — https://docs.gitlab.com/api/repositories/ — archive endpoint with `sha` and `path`. [fetched]
39. [S39] "Using Git submodules with GitLab CI/CD" — https://docs.gitlab.com/ci/runners/git_submodules/ — `GIT_SUBMODULE_STRATEGY`, relative URLs, job-token access, update flags. [fetched]
40. [S40] "Pull mirroring" — https://docs.gitlab.com/user/project/repository/mirror/pull/ — Premium/Ultimate, 30-minute interval, trigger-pipelines option and credentials warning. [fetched]
41. [S41] "Scheduled pipelines" — https://docs.gitlab.com/ci/pipelines/schedules/ — all tiers, cron, inputs/variables, instance frequency limit. [fetched]
42. [S42] "CI/CD components" — https://docs.gitlab.com/ci/components/ — all tiers, `include: component` with version, `spec:inputs`, catalog publishing. [fetched]
43. [S43] "CI/CD variables" — https://docs.gitlab.com/ci/variables/ — group variables (Owner), masked/protected, inheritance, precedence. [fetched]
44. [S44] "Predefined CI/CD variables" — https://docs.gitlab.com/ci/variables/predefined_variables/ — `CI_PIPELINE_SOURCE`, `CI_PAGES_URL` (path_prefix from 17.9), `CI_PAGES_HOSTNAME`, `CI_PROJECT_PATH_SLUG`, `TRIGGER_PAYLOAD`. [fetched]
45. [S45] "Webhooks" — https://docs.gitlab.com/user/project/integrations/webhooks/ — push-event branch filter, custom headers (20), group webhooks Premium/Ultimate. [fetched]
46. [S46] "Group access tokens" — https://docs.gitlab.com/user/group/settings/group_access_tokens/ — Premium/Ultimate on GitLab.com, any licence self-managed, bot user, expiry. [fetched]
47. [S47] "Compute minutes" — https://docs.gitlab.com/ci/pipelines/compute_minutes/ — Free 400 minutes/month, paid tiers higher (numbers not on page), self-managed quota disabled by default. [fetched]
48. [S48] "Wiki", "Wiki-specific Markdown", "Group wikis" — https://docs.gitlab.com/user/project/wiki/ , https://docs.gitlab.com/user/project/wiki/markdown/ , https://docs.gitlab.com/user/project/wiki/group/ — per-project git repo, formats, `[[Home]]` links, `[wiki_page:namespace/project:Home]`, group wikis Premium/Ultimate. [fetched]
49. [S49] `backstage/mkdocs-monorepo-plugin` — https://github.com/backstage/mkdocs-monorepo-plugin — `!include`, submodules for multi-repo, Apache-2.0, 399★. [fetched]
50. [S50] `jdoiro3/mkdocs-multirepo-plugin` — https://github.com/jdoiro3/mkdocs-multirepo-plugin — `!import`, `GitlabCIJobToken`, MIT, 195★, "Project Status: Inactive". [fetched]
51. [S51] Material for MkDocs and its `projects` plugin — https://squidfunk.github.io/mkdocs-material/ and https://squidfunk.github.io/mkdocs-material/plugins/projects/ — MIT, browser search, projects plugin deprecated ("impossible to maintain"). [fetched]
52. [S52] Antora docs — https://docs.antora.org/antora/latest/ , https://docs.antora.org/antora/latest/playbook/configure-content-sources/ , https://docs.antora.org/antora/latest/install-and-run-quickstart/ — AsciiDoc-only, playbook content sources, MPL-2.0, Antora 3.2, Node 24 recommended. [fetched]
53. [S53] Backstage TechDocs — https://backstage.io/docs/features/techdocs/ , …/architecture , …/configuring-ci-cd , …/creating-and-publishing — docs-like-code, GitLab supported, recommended CI + object storage, `techdocs-cli generate/publish`, `backstage.io/techdocs-ref`. [fetched]
54. [S54] Docusaurus — https://docusaurus.io/docs , https://docusaurus.io/docs/docs-multi-instance , https://api.github.com/repos/facebook/docusaurus — v3.10.2, MDX, multi-instance docs, size caveat, MIT, 66,157★. [fetched]
55. [S55] Obsidian Help: Links, Properties, Bases — https://obsidian.md/help/links , https://obsidian.md/help/properties , https://obsidian.md/help/bases — wikilink forms and folder paths from vault root, default properties and types, Bases views. [fetched]
56. [S56] Karpathy, "llm-wiki" gist (2026-04-04) as summarised in `../background/landscape.md` §1 — `index.md`/`log.md`, Obsidian as IDE, `qmd` search. [fetched in background]
57. [S57] `../background/problems-and-fixes.md` — P01, P05, P06, P10, P11, P12, P13, P14, P16, P19, P23, P24; D01, D04, D06, D09–D11, D16, D18, D20; SOLAR_FIELDS Quartz + Decap CMS remark. [fetched in background]
58. [S58] Sibling ADRs `ADR-07-google-okf-and-agent-context-standards.md`, `ADR-08-hybrid-deterministic-backbone-plus-llm-narrative.md`, `ADR-10-gitlab-native-duo-and-gitlab-wiki.md` (§3.7 and §4 hub assumptions). [fetched]
59. [S59] Google Open Knowledge Format SPEC v0.2 (absolute links from bundle root; consumers tolerate broken links) as summarised in `../background/landscape.md` §6. [fetched in background]
60. [S60] llms.txt specification (llmstxt.org) as summarised in `../background/landscape.md` §8. [fetched in background]
61. [S61] Obsidian setting "New link format" (shortest path / relative / absolute) — [memory] ❓ (the fetched Links page did not include it; verify in Obsidian Settings > Files and links).
62. [S62] Quartz v4 graph rendering stack (pixi.js / d3) — [memory] ❓ (not needed for the decision; v5 graph is a separate plugin).
63. [S63] GitLab.com Premium/Ultimate compute-minute quotas (10,000 / 50,000 per month) — [memory] ❓ (the fetched page only states "Paid tiers receive a higher monthly quota").
