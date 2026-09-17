---
type: Analysis
id: {{id_prefix}}/analyses/{{slug}}
schema_version: 1
title: {{title}}
description: {{description}}
audience: [agent, dev]
owner: agent
tags: [analysis]
sources:
  - { id: {{source_id}}, resource: "repo://{{path}}", title: {{source_title}} }
last_verified_commit: {{head}}
generated: { by: "copilot-cli/{{model}}", at: {{date}} }
status: draft
related: []
---
# {{title}}
**Read this when:** …

## Question
…

## Answer
…[^{{source_id}}]

## Evidence
| Statement | Where |
|---|---|
| … | `{{path}}` |

## Open questions
- …

[^{{source_id}}]: …
