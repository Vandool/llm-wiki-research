---
type: Conventions
id: {{id_prefix}}/conventions
schema_version: 1
title: Conventions and glossary
description: Canonical vocabulary, naming rules, heading order per page type and citation rules that every page of this wiki follows.
audience: [agent, dev]
owner: both
sources: []
last_verified_commit: {{head}}
generated: { by: "copilot-cli/{{model}}", at: {{date}} }
status: draft
---
# Conventions and glossary
**Read this when:** creating or changing any page.

## Glossary
Use the canonical term in prose; identifiers, endpoint paths, topic values, configuration names and model names in backticks exactly as in the code. State an alias once here, never interchangeably in prose.

| Canonical term | Definition and alias policy | Code location |
|---|---|---|
| **{{site_title}}** | … | … |

## Naming
- File names lowercase kebab-case, one thing per page: `modules/<module>.md`, `concepts/<concept>.md`, `howto/<task>.md`, `runbooks/<situation>.md`, `api/<router>-guide.md`, `product/<feature>.md`.
- HTTP operations as `METHOD /path` including the version prefix; never a bare path.
- Topics, queues, tables, flags and environment variables are deployment configuration: name the concept, put the selector in backticks, never a value.
- Statuses and enum values as their exact code values in backticks.
- Repository references as repository-relative paths in backticks: `src/orders/service.py`; symbols as `src/orders/service.py::OrderService.place`.

## Page templates (heading order per type)
| Type | Heading order |
|---|---|
| Module | lede **Does / Exposes / Emits / Consumes** → ## Structure → ## Configuration → ## Tests → ## Gotchas |
| Concept | **Problem** → **Solution here** → **Consequences** → **Where to look** |
| How-to | ## Goal → ## Steps → ## Validation → ## Related code |
| Runbook | ## Trigger → ## Steps → ## Verify → ## Escalate |
| Architecture | ## Context → ## Containers → ## Runtime flows → ## Deployment |
| Contract Guide | ## Purpose → ## Callers → ## Semantics → ## Errors → ## Versioning |
| Feature | **In plain words** → ## Who uses it → ## How it behaves → ## Limits and known issues → ## What changed recently → ## Related features → ## For developers |
| Analysis | ## Question → ## Answer → ## Evidence → ## Open questions |

Every page: `# <title>`, a two or three sentence summary, a `**Read this when:**` line (Feature pages: **In plain words** instead), then the headings above in that order; omit a heading that has no evidence.

## Citation microformat
- `sources[]` entries are `{ id, resource, title }`. `resource` schemes: `repo://path`, `repo://path#La-Lb` (line range), `repo://path::Symbol` (one definition), `api://<api-id>[/<operationId>]`, `event://<channel>`, `adr://NNNN`, `changelog://<scope>@<from>..<to>`, `flag://<key>`, `https://…`.
- Every technical claim ends with a footnote `[^id]` whose `id` is a `sources[].id`; the footnote text names the symbol, line range or operation that backs the claim.
- Inline code references use `path/file.py::Symbol`. A wiki page or the log is never a source.
- Mark what the code does not settle as **Needs confirmation**; never infer a topic name, caller, authorization outcome, ordering or idempotency from naming alone.

## Operational invariants to state consistently
- …
