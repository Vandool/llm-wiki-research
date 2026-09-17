---
type: Instructions
id: {{id_prefix}}/instructions
schema_version: 1
title: Wiki instructions for {{repo_slug}}
description: Project-specific steering for the wiki agent. Edit freely; every section is optional except 1 and 3.
audience: [agent, dev]
owner: human
generated: { by: "human:{{user}}", at: {{date}} }
---
# Wiki instructions
<!-- Read by the wiki agent on every run; excluded from the published site. Keep under 300 lines.
     Rules here override the page templates and the default conventions. -->

## 1. Identity and purpose
- Canonical name of this system: … · Aliases used in code or deployment (state once in the glossary): …
- One paragraph: what it does, why it exists, who depends on it.

## 2. Audiences (tick what applies; order = priority)
- [x] Coding agents (planning, implementation, testing, bug fixing)   - [x] Developers   - [ ] Product owners (enables `product/`)
- Language: English.

## 3. Must-cover areas, in priority order
<!-- Delete rows that do not apply. "Required sections" are the fixed heading order the template enforces. -->
| # | Area | Folder | Required sections | Notes for this project |
|---|---|---|---|---|
| 1 | Overview | overview.md | What it is · Who uses it · How a request flows · Where to start | |
| 2 | Architecture | architecture/ | Context · Containers · Runtime flows · Deployment | name the flows below |
| 3 | Modules | modules/ | Does/Exposes/Emits/Consumes lede · Structure · Configuration · Tests · Gotchas | one page per … |
| 4 | Concepts | concepts/ | Problem · Solution here · Consequences · Where to look | |
| 5 | Flows / workflows | howto/ | Goal · Steps · Validation · Related code | |
| 6 | API | api/ (generated) + `<router>-guide.md` | Purpose · Callers · Semantics · Errors · Versioning | spec file: … |
| 7 | Events | events/ (generated) + guides | Direction · Contract · Delivery semantics · Configuration | |
| 8 | Data | concepts/ or modules/ | Models · Stores · Ownership · Migrations | |
| 9 | Configuration | modules/*#Configuration | name, type, default, where read — names only, never values | |
| 10 | Operations / runbooks | runbooks/ | Trigger · Steps · Verify · Escalate | |
| 11 | Testing | howto/testing.md | How tests are organised · Run · Add | |
| 12 | Decisions | decisions/ (generated) | — | ADR location: … |
| 13 | Product | product/ | Feature template | only when the PO audience is ticked |

## 4. Must-include concepts (one per line; each becomes a Concept page)
- …

## 5. Must-include flows (one per line; each becomes a How-to or an Architecture "Runtime flows" entry)
- …

## 6. What deliberately gets no page (negative space)
- path or topic — reason

## 7. Exclusions (never read, never cite)
- generated or vendored code, fixtures, secrets, … (globs also live in .github/wiki.config.json)

## 8. Glossary seeds
| Term | Plain definition | Aliases in code | Code location |
|---|---|---|---|

## 9. Naming rules
- File names lowercase kebab-case; endpoints as `METHOD /path`; identifiers in backticks exactly as in code; cite code as `path/file.py::Symbol`.

## 10. Update-run rules
- Change only pages whose sources changed; never restructure or rename during an update; update the glossary when a term changes; if code and a page disagree, the code is right — fix the page and log it.

## 11. First-run (bootstrap) rules
- Compile `conventions.md` first, then leaves before overviews; mark uncertainty as **Needs confirmation**; list the three places understood least in the final log entry.

## 12. Always-apply rules
- Every claim cites code; never cite another wiki page or the log; no secrets, tokens, hostnames, customer identifiers; code blocks ≤ 10 lines; omit empty sections; 150–400 words per Module page; if the wiki has no established statement on X, say so, never synthesise.

## 13. "Needs confirmation" policy
- Use the literal token **Needs confirmation** on the page and in the log; never infer topic names, callers, auth outcomes, ordering or idempotency from naming alone.

## 14. Product-owner layer rules (when enabled)
- `audience: [po]`; sentences ≤ 25 words; no code, paths, or the forbidden vocabulary; one "In plain words" paragraph before any table; cite behaviour (`api://`, `event://`, `changelog://`), never files.

## 15. Known unknowns (filled by /wiki-init from the module map review)
- …
