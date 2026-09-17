---
type: Module
id: sample/modules/broken
schema_version: 1
title: Broken links
description: One broken link (L01) and three bad link forms (L08).
audience: [agent, dev]
owner: agent
sources: [{ id: api, resource: "repo://src/orders/api.py" }]
last_verified_commit: 0000000000000000000000000000000000000000
generated: { by: "copilot-cli/gpt-5-mini", at: 2026-09-01T09:00:00Z }
status: draft
---
# Broken links
**Read this when:** testing the linter.[^api]
- [missing page](nope.md)
- [[Orders service]]
- [absolute](/wiki/modules/orders.md)
- [escapes the wiki](../../src/orders/api.py)
- [no extension](orders)

[^api]: router
