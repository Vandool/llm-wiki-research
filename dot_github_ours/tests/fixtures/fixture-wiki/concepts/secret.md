---
type: Concept
id: sample/concepts/secret
schema_version: 1
title: Leaked secret
description: Contains a fake AWS key (L05), a zero-width space and an HTML comment (L14).
audience: [agent, dev]
owner: agent
sources: [{ id: clock, resource: "repo://src/common/clock.py" }]
last_verified_commit: 0000000000000000000000000000000000000000
generated: { by: "copilot-cli/gpt-5-mini", at: 2026-09-01T09:00:00Z }
status: draft
---
# Leaked secret
**Problem.** Someone pasted AKIAIOSFODNN7EXAMPLE into a page.[^clock]
**Solution here.** Zero​width space hidden here.
<!-- a stray HTML comment -->
**Consequences.** none.
**Where to look.** `src/common/clock.py`.

[^clock]: clock
