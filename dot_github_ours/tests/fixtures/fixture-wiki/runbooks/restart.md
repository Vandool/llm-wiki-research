---
type: Runbook
id: sample/runbooks/restart
schema_version: 1
title: Restart the service
description: Marked stable without a human verification (L16).
audience: [dev]
owner: agent
sources: [{ id: api, resource: "repo://src/orders/api.py" }]
last_verified_commit: 0000000000000000000000000000000000000000
generated: { by: "copilot-cli/gpt-5-mini", at: 2026-09-01T09:00:00Z }
status: stable
---
# Restart the service
## Trigger
Alerts fire.[^api]
## Steps
Restart.
## Verify
Health is green.
## Escalate
Page the team.

[^api]: router
