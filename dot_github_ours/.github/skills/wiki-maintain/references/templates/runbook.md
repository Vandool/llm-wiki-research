---
type: Runbook
id: {{id_prefix}}/runbooks/{{slug}}
schema_version: 1
title: {{title}}
description: {{description}}
audience: [dev, agent]
owner: agent
team: "@{{team}}"
tags: [runbook]
sources:
  - { id: {{source_id}}, resource: "repo://{{path}}", title: {{source_title}} }
last_verified_commit: {{head}}
generated: { by: "copilot-cli/{{model}}", at: {{date}} }
status: draft
related: []
---
# {{title}}
**Read this when:** …

## Trigger
…[^{{source_id}}]

## Steps
1. …

## Verify
…

## Escalate
…

[^{{source_id}}]: …
