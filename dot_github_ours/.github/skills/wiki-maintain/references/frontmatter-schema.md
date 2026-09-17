# Frontmatter schema (OKF v0.2 + kit extensions, `schema_version: 1`)

Lint L06 checks every page against this file; `lint.py --fix` repairs only the `id`.

## Required on every page
| Key | Value |
|---|---|
| `type` | one of the `type` enum below |
| `title` | ≤80 characters; equals the H1 |
| `description` | one line, ≤200 characters; becomes the index entry and link preview |
| `id` | `<id_prefix>/<path-without-.md>` (`repo.id_prefix` in the config), e.g. `orders/modules/orders` |
| `schema_version` | `1` |
| `audience` | non-empty list ⊂ `[agent, dev, po]` |
| `owner` | `human` \| `agent` \| `process` \| `both` |
| `generated` | `{ by: <actor>, at: <ISO 8601 instant> }` |

## Conditional
- `owner: agent` or `owner: process` ⇒ `sources` (list, may be empty only on Overview/Conventions/Glossary) and `last_verified_commit` (40-hex SHA) are required.
- `po` in `audience` ⇒ no `repo://` source; body follows the PO rules (`wiki.instructions.md` §6).
- `status: stable` on Contract Guide, Runbook, Feature, Release Notes ⇒ a `human:` entry in `verified` (L16).
- Folder `index.md`: `title` only. Root `index.md`: `okf_version: "0.2"` and `title` only.

## Optional
`resource` (canonical asset URI) · `tags` (lowercase, `/` for hierarchy) · `verified` (list of `{ by, at }`; never edited by the agent) · `status` (`draft` \| `stable` \| `deprecated`; absent = stable; agent-created pages set it explicitly) · `stale_after` (ISO instant; Runbook 180 d, Feature 90 d, Overview 180 d) · `team` (`"@group/team"`, quoted) · `provides`, `consumes` (lists of `api:<id>` / `event:<channel>`) · `related` (list of page ids) · `capability` (Feature only) · `aliases` (old slugs, Quartz redirects).

## `sources[]` items
`{ id: <a-z0-9->, resource: "<scheme>://…", title: "…" }`; `id` unique per page and the footnote key `[^id]`.

| Scheme | Form | Hashed for staleness |
|---|---|---|
| `repo` | `repo://path`, `repo://path#La-Lb`, `repo://path::Symbol` | yes (blob, line range, symbol) |
| `api` | `api://<api-id>[/<operationId>]` | yes (spec file) |
| `event` | `event://<channel>` | yes (AsyncAPI file) |
| `adr` | `adr://NNNN` | yes (ADR file) |
| `changelog` | `changelog://<scope>@<from>..<to>` | no |
| `flag` | `flag://<key>` | no |
| `https` / `http` | full URL | no |

## Actors (`generated.by`, `verified[].by`)
`copilot-cli/<model>` (the agent) · `process:<script>/<ver>` (a kit script, e.g. `process:facts.py/1.0.0`) · `human:<gitlab-user>`.

## Enumerations (closed; a change bumps `schema_version`)
| Enum | Values |
|---|---|
| `type` | Conventions, Instructions, Requests, Overview, Architecture, Module, Concept, How-to, Contract, Contract Guide, Runbook, Glossary, Feature, Capability Map, Release Notes, What Changed, Analysis, Generated, Log Archive (`Service` is reserved for a hub) |
| `status` | draft, stable, deprecated |
| `audience` | agent, dev, po |
| `owner` | human, agent, process, both |
| log actions | Bootstrap, Creation, Update, Deprecation, Lint, Query, Instruction, Deferred |
| request states | OPEN, DONE, SKIPPED, DEFERRED |
| stale reasons | blob_changed, lines_changed, symbol_changed, symbol_missing, missing_source, renamed, expired |

## Who owns which page (`owner`)
| Owner | Pages | Who edits |
|---|---|---|
| `process` | every `index.md`, `generated/**`, `api/<router>.md`, `events/<channel>.md`, `decisions/index.md`, `log.md` | scripts only |
| `human` | `instructions.md` | people; the agent only during `/wiki-init` |
| `both` | `conventions.md`, `glossary.md`, `requests.md` (script-managed lines), `catalog.yaml`, Feature pages | people and the agent, section by section |
| `agent` | narrative pages: Overview, Architecture, Module, Concept, How-to, Runbook, Contract Guide, Analysis | the agent; people review |

## Forbidden keys
`date`, `created`, `modified`, `updated`, `lastmod`, `published`, `image`, `cover`, `permalink`, `draft` carry Quartz semantics and must not appear in a page for any other meaning (`draft` is expressed as `status: draft`). Keys not listed above are warnings.

## YAML subset the scripts parse
`key: value` scalars; quoted strings (`"…"`); block lists (`- item`, `- { id: x, resource: "…", title: "…" }`); flow lists (`[a, b]`); flow maps (`{ by: "…", at: … }`); nested block maps. Not supported: anchors, `|`/`>` multi-line scalars, tabs, comments inside flow collections. Quote any scalar containing `:`, `,`, `{`, `}`, `[`, `]` or `#`.

## Page templates
`references/templates/<type>.md`, rendered by `template.py <Type> --vars k=v …`. Placeholders: `id_prefix`, `slug`, `title`, `description`, `source_id`, `path`, `source_title`, `team`, `head`, `model`, `date`; Contract Guide adds `api_id`; Feature adds `capability` and `source_resource` (a full non-`repo://` URI); Conventions uses `site_title`.
