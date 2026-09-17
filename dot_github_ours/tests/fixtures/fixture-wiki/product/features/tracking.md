---
type: Feature
id: sample/product/features/tracking
schema_version: 1
title: Order tracking
description: PO page with leakage (L07).
audience: [po]
owner: both
sources: [{ id: ev, resource: "event://orders.placed" }, { id: code, resource: "repo://src/orders/api.py" }]
last_verified_commit: 0000000000000000000000000000000000000000
generated: { by: "copilot-cli/gpt-5-mini", at: 2026-09-01T09:00:00Z }
status: draft
---
# Order tracking

| Status | Meaning |
|---|---|
| placed | the endpoint accepted the order |

## Who uses it
Customers who want to know where their order is right now can open the page and look at the status which is updated many times per day by the background process that runs in the cluster.

## How it behaves
```python
print("code on a PO page")
```
See `src/orders/api.py` for details.
