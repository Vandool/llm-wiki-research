---
applyTo: "wiki/**"
description: Authoring contract for wiki pages (frontmatter, links, evidence, size, PO style). Negative constraints; the reasons are in wiki/conventions.md.
---
# Wiki authoring contract

Applies to every file under the wiki directory. Project-specific rules (`wiki/instructions.md`) and the
canonical vocabulary (`wiki/conventions.md`) override the defaults here; the negative rules do not bend.

## 1. Never
- No `[[wikilinks]]`; no bundle-absolute links (`/modules/x.md`); no link that leaves the wiki directory
  (`../src/…`); no relative link without the `.md` extension.
- No editing of generated files (`index.md`, `log.md`, `generated/**`, `api/<router>.md`,
  `events/<channel>.md`, `decisions/index.md`, `.manifest.json`, `.wiki-plan.json`) or of pages with
  `owner: human` or `owner: process`.
- No code fence longer than 10 lines; the wiki explains, it does not duplicate code.
- Omit empty sections rather than padding them with filler.
- You write for a model and for a new developer — not for marketing. Dense, precise, no introductory
  throat-clearing. No praise for the system itself.
- No wiki page and no log entry as a source or as evidence for a claim.
- No Quartz keys (`date`, `created`, `modified`, `updated`, `lastmod`, `published`, `image`, `cover`,
  `permalink`, `draft`) for any other meaning.
- No hidden Unicode (zero-width, tag or bidi characters) and no HTML comments other than the managed
  markers (`<!-- WIKI-AGENT:START/END -->`, generated-block markers).
- No secrets, tokens, credentials, hostnames, customer identifiers or environment variable values;
  configuration is documented by name only.
- No identifier, endpoint, topic, table, flag or symbol that was not seen in the code or a generated page.

## 2. Frontmatter contract
- Required on every page: `type`, `title`, `description`, `id`, `schema_version`, `audience`, `owner`,
  `generated: { by, at }`.
- Conditional: `owner: agent|process` also needs `sources[]` and `last_verified_commit`;
  `po` in `audience` forbids `repo://` sources.
- Actors: `copilot-cli/<model>`, `process:<script>/<ver>`, `human:<user>`.
- `id` = `<id_prefix>/<path-without-.md>`; it never changes while the file stays where it is.
- New pages carry `status: draft`; the agent never sets `stable`. `verified` is never touched by the
  agent; a human adds entries in review.
- Full key list, enumerations and the YAML subset the scripts parse:
  `.github/skills/wiki-maintain/references/frontmatter-schema.md`.

## 3. Page shape
- H1 equals `title`. Then a two or three sentence summary, then a `**Read this when:**` line that names
  the tasks the page serves (Feature pages: an **In plain words** paragraph instead).
- Fixed heading order per type (`wiki/conventions.md`, "Page templates"): Module = lede
  **Does / Exposes / Emits / Consumes** → Structure → Configuration → Tests → Gotchas; Concept =
  Problem → Solution here → Consequences → Where to look; How-to = Goal → Steps → Validation → Related
  code; Runbook = Trigger → Steps → Verify → Escalate; Architecture = Context → Containers → Runtime
  flows → Deployment; Contract Guide = Purpose → Callers → Semantics → Errors → Versioning.
- Module pages: 150–400 words. One topic per page; extend an existing page rather than creating a
  near-duplicate.
- Every technical claim ends with a footnote `[^id]` whose `id` is one of the page's `sources[].id`;
  the footnote names the symbol, line range or operation behind the claim. Inline references use
  `path/file.py::symbol`.
- Mermaid only for a runtime flow, state lifecycle or data relationship whose every node and edge was
  read in the code, followed by a one-line caption; never decorative.
- What the code does not settle is marked **Needs confirmation** on the page; never infer a topic name,
  caller, authorization outcome, ordering or idempotency guarantee from naming alone.

## 4. Links
- File-relative markdown links with the `.md` extension: `[Orders service](../modules/orders.md)`.
- Code is linked as a full GitLab blob URL or written as a backticked path `src/orders/api.py::router`;
  never as a relative link out of the wiki.
- Every new page needs at least one inbound link from a topically adjacent page; links from an
  `index.md` do not count.
- Cross-repository references are full GitLab URLs; other services are described at the boundary
  only (section 7).

## 5. Size caps (body lines, L04)
| Type | Max | Type | Max | Type | Max |
|---|---|---|---|---|---|
| Overview | 150 | Architecture | 200 | Module | 200 |
| Concept | 120 | How-to | 120 | Contract | 400 |
| Contract Guide | 150 | Runbook | 150 | Glossary | 300 |
| Feature | 80 | Capability Map | 150 | Release Notes | 200 |
| What Changed | 60 | Analysis | 200 | Generated | 400 |
| Conventions | 150 | Requests | 400 | Instructions | 300 |
Root `index.md` ≤120 lines, folder indexes ≤200 (sharded by the generator).

## 6. Product-owner pages (`audience: [po]`, folder `product/`)
- Sentences of at most 25 words; plain English; no code fences, file paths or `repo://` sources.
- Forbidden vocabulary: endpoint, repository, MR, merge request, JSON, null, exception, refactor, schema,
  payload, identifier(s), stack trace, commit (list in `po.forbidden_words` of the config).
- One **In plain words** paragraph before any table or list.
- Cite behaviour (`api://`, `event://`, `changelog://`), never files; sections What it does · Who uses it ·
  How it behaves · Limits and known issues · What changed recently · Related features · For developers.

## 7. Boundaries
Where something crosses into another service, describe the boundary and what this service assumes; not
the other service's internals. Contracts (API, events, schemas) are the facts that matter most: keep
them exact and tied to the spec or the code that defines them.

## 8. Minimal diff and contradictions
- When updating a page, touch only the affected sections; do not rewrite unchanged passages.
- If the code and a page disagree, the code is right: replace the statement, add a dated line under
  "Invariants and pitfalls" saying what the page stated until which commit, and name it in the log entry.
