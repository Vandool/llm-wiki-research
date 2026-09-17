---
type: Module
id: sample/modules/payments
schema_version: 1
title: Payments adapter
description: Orphan module page (L02) citing an unknown symbol and a missing path (L13).
audience: [agent, dev]
owner: agent
sources: [{ id: gw, resource: "repo://src/payments/gateway.py::FakeGateway.refund" }, { id: missing, resource: "repo://src/payments/nowhere.py" }]
last_verified_commit: 0000000000000000000000000000000000000000
generated: { by: "copilot-cli/gpt-5-mini", at: 2026-09-01T09:00:00Z }
status: draft
---
# Payments adapter
**Read this when:** you touch payments. `src/payments/gateway.py::FakeGateway.charge` exists but `src/payments/gateway.py::FakeGateway.refund` does not.[^gw]

[^gw]: gateway
