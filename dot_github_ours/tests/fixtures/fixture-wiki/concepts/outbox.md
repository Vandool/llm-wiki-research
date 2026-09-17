---
type: Concept
id: sample/concepts/outbox
schema_version: 1
title: Transactional outbox
description: Why events go through an outbox table.
audience: [agent, dev]
owner: agent
sources: [{ id: outbox, resource: "repo://src/common/events.py::Outbox" }]
last_verified_commit: 0000000000000000000000000000000000000000
generated: { by: "copilot-cli/gpt-5-mini", at: 2026-09-01T09:00:00Z }
status: draft
---
# Transactional outbox
**Problem.** Dual writes lose events.[^outbox]
**Solution here.** `src/common/events.py::Outbox` buffers them. See [secrets](secret.md), [too long](toolong.md).
**Consequences.** at-least-once.
**Where to look.** `src/common/events.py`.

[^outbox]: outbox class
