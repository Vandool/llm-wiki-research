---
name: wiki-page
description: >-
  Write the pages of ONE cluster from wiki/.wiki-plan.json during bootstrap: reads the cluster spec,
  the conventions, already-written dependency pages and the budgeted source excerpts, writes the pages
  from the templates, verifies and marks the cluster done or deferred. Use only when given a cluster id
  by the bootstrap driver or the user. Do not use for incremental updates.
argument-hint: "<cluster-id>"
allowed-tools: [read, edit, search, execute]
---
# /wiki-page <cluster-id> — write one planned cluster

Procedure only, no STOP points: the skill runs headlessly under the bootstrap driver and behaves the
same interactively. Authoring rules: `.github/instructions/wiki.instructions.md`; script flags:
`.github/skills/wiki-maintain/SKILL.md`. `S/<name>.py` = `python3 .github/skills/wiki-maintain/scripts/<name>.py`.
The driver commits; you never do.

## 1. Cluster spec
- `S/plan.py show <cluster-id> --json` → `title`, `kind`, `deps`, `pages[{path,type,audience,owner,
  sources[],notes}]`, `estimate`. A cluster whose status is not `pending` or `running`: report it,
  result line `"status":"failed"`, stop.
- The run context (injected, else `S/run.py status --json`) carries the pre-built source packs
  (`work[].sources[].bytes`, hunks) and `budget`.

## 2. Context, in this order and nothing more
1. `wiki/conventions.md` (canonical terms, heading order per type, citation microformat).
2. `wiki/glossary.md`.
3. At most three pages written by dependency clusters (`deps`), chosen by the `related`/`sources`
   overlap with this cluster; read them for links and terms, not as evidence.
4. The generated pages that belong to the cluster's paths: `wiki/generated/inventory.md` (the
   sub-tree), the matching `wiki/api/<router>.md` and `wiki/events/<channel>.md` when the page spec
   names them.

## 3. Sources within the cluster budget
For every `sources[]` entry of every page: `S/excerpt.py <path> --lines a-b` for ranged resources,
`S/excerpt.py <path> --symbol NAME` for `::Symbol` resources, `S/excerpt.py <path> --lines 1-120`
otherwise; larger files by their top-level symbols (from `wiki/generated/symbols.json`), never whole.
Read the leaves (utilities, models) before the modules that use them. Stop reading when a page has
enough evidence for every heading its type requires.

## 4. Write the pages
- Per page: `S/template.py <Type> --vars id_prefix=… slug=… title=… description=… source_id=… path=…
  source_title=… team=… head=… model=… date=…` → fill every heading in the template's order; omit a
  heading that has no evidence rather than padding it.
- Frontmatter: `status: draft`, `sources[]` = exactly the resources you read (id = footnote key),
  `last_verified_commit` = the run's `head`, `generated.by` = `copilot-cli/<model>` from the context.
- Body: `# <title>`, two or three sentence summary, `**Read this when:**` lede, a footnote `[^id]` on
  every technical claim, inline `path/file.py::symbol`, **Needs confirmation** where the code is
  ambiguous, Module pages 150–400 words, code blocks ≤10 lines.
- Links: file-relative `.md` to pages that exist or are planned (the plan makes them valid targets);
  at least one link between the pages of this cluster and one to a dependency page.
- Budget exhausted (`excerpt.py` exit 3 or guard denial): finish the page you are on if its evidence is
  already read, write no further page, continue at step 5 with `deferred`.

## 5. Verify
`S/index.py --write` → `S/lint.py --changed --json` → `S/backlinks.py --changed --json --plan
wiki/.wiki-plan.json` → fix findings on the pages you wrote, rerun until clean. Pages that cannot be made
clean are deleted from your result and reported (the driver keeps only lint-clean pages).

## 6. Mark and end
- All pages written and clean → `S/plan.py mark <cluster-id> done`.
- Budget ran out → `S/plan.py mark <cluster-id> deferred --reason "<pages left>: <why>"`;
  the clean pages stay.
- `S/log.py add --action Creation --text "cluster <cluster-id>: <n> pages; needs confirmation: <k>"
  --run-id <run_id>`; prose summary (the three least certain statements; proposals for pages the plan
  lacks) → the single `WIKI-RUN-RESULT` line (`created` = pages written, `status` ok or deferred).

## Do not
Write a page the cluster spec does not list; edit pages of other clusters (link to them instead);
read `wiki/log.md`; cite a wiki page as evidence; promote anything to `stable`; run `git` write
commands or `manifest.py` (the driver does).
