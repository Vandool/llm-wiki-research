---
type: Feature
id: {{id_prefix}}/product/{{slug}}
schema_version: 1
title: {{title}}
description: {{description}}
audience: [po]
owner: both
team: "@{{team}}"
capability: {{capability}}
tags: [po]
sources:
  - { id: {{source_id}}, resource: "{{source_resource}}", title: {{source_title}} }
last_verified_commit: {{head}}
generated: { by: "copilot-cli/{{model}}", at: {{date}} }
status: draft
related: []
---
# {{title}}

**In plain words.** …

## Who uses it
…

## How it behaves
- …[^{{source_id}}]

## Limits and known issues
- …

## What changed recently
- {{date}} — …[^{{source_id}}]

## Related features
…

## For developers
[…](../modules/….md)

[^{{source_id}}]: …
