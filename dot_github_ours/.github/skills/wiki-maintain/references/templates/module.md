---
type: Module
id: {{id_prefix}}/modules/{{slug}}
schema_version: 1
title: {{title}}
description: {{description}}
audience: [agent, dev]
owner: agent
team: "@{{team}}"
tags: []
provides: []
consumes: []
sources:
  - { id: {{source_id}}, resource: "repo://{{path}}", title: {{source_title}} }
last_verified_commit: {{head}}
generated: { by: "copilot-cli/{{model}}", at: {{date}} }
status: draft
related: []
---
# {{title}}
**Read this when:** …
**Does:** … **Exposes:** … **Emits:** … **Consumes:** …

## Structure
| Component | Path | Responsibility |
|---|---|---|

## Configuration
## Tests
## Gotchas

[^{{source_id}}]: …
