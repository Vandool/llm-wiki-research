---
type: Architecture
id: {{id_prefix}}/architecture/{{slug}}
schema_version: 1
title: {{title}}
description: {{description}}
audience: [agent, dev]
owner: agent
team: "@{{team}}"
tags: [architecture]
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

## Context
…[^{{source_id}}]

## Containers
| Container | Responsibility | Code |
|---|---|---|
| … | … | `{{path}}` |

## Runtime flows
### …
1. …

## Deployment
…

[^{{source_id}}]: …
