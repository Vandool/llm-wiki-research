---
type: Module
id: sample/modules/orders
schema_version: 1
title: Orders service
description: Owns the order lifecycle from draft to paid.
audience: [agent, dev]
owner: agent
sources: 
  - { id: service, resource: "repo://src/orders/service.py::OrderService.place", title: place }
  - { id: api, resource: "repo://src/orders/api.py", title: HTTP }
last_verified_commit: 0000000000000000000000000000000000000000
generated: { by: "copilot-cli/gpt-5-mini", at: 2026-09-01T09:00:00Z }
status: stable
---
# Orders service
**Read this when:** you change orders.
**Does:** moves orders through the state machine in `src/orders/service.py::OrderService.place`.[^service] **Exposes:** the router.[^api]

## Structure
| Component | Path | Responsibility |
|---|---|---|
| API | `src/orders/api.py` | handlers[^api] |

## Gotchas
See [Broken links](broken.md). The payments page is deliberately not linked from anywhere (L02).

[^service]: `OrderService.place`
[^api]: router
