---
type: Contract Guide
id: {{id_prefix}}/api/{{slug}}-guide
schema_version: 1
title: {{title}}
description: {{description}}
audience: [agent, dev]
owner: agent
team: "@{{team}}"
tags: [api]
sources:
  - { id: spec, resource: "api://{{api_id}}", title: "API specification {{api_id}}" }
  - { id: {{source_id}}, resource: "repo://{{path}}", title: {{source_title}} }
last_verified_commit: {{head}}
generated: { by: "copilot-cli/{{model}}", at: {{date}} }
status: draft
related: [{{id_prefix}}/api/{{slug}}]
---
# {{title}}
**Read this when:** … Endpoint table and schemas: [{{slug}}]({{slug}}.md) (generated).

## Purpose
…[^spec]

## Callers
…

## Semantics
…[^{{source_id}}]

## Errors
| Status | When |
|---|---|
| … | … |

## Versioning
…

[^spec]: …
[^{{source_id}}]: …
