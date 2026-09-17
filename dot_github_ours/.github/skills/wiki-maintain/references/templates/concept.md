---
type: Concept
id: {{id_prefix}}/concepts/{{slug}}
schema_version: 1
title: {{title}}
description: {{description}}
audience: [agent, dev]
owner: agent
tags: []
sources:
  - { id: {{source_id}}, resource: "repo://{{path}}", title: {{source_title}} }
last_verified_commit: {{head}}
generated: { by: "copilot-cli/{{model}}", at: {{date}} }
status: draft
related: []
---
# {{title}}
**Read this when:** …

**Problem.** …
**Solution here.** …[^{{source_id}}]
**Consequences.** …
**Where to look.** `{{path}}`

[^{{source_id}}]: …
