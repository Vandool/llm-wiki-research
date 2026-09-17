---
type: How-to
id: sample/howto/deploy
schema_version: 1
title: Deploy
description: How to deploy the service.
audience: [dev, agent]
owner: agent
sources: [{ id: ci, resource: "repo://.gitlab-ci.yml" }]
last_verified_commit: 0000000000000000000000000000000000000000
generated: { by: "copilot-cli/gpt-5-mini", at: 2026-09-01T09:00:00Z }
status: draft
---
# Deploy
## Goal
Ship it.[^ci]
## Steps
1. Push. See [Restart](../runbooks/restart.md).
## Validation
Pipeline green.
## Related code
`.gitlab-ci.yml`

[^ci]: pipeline
