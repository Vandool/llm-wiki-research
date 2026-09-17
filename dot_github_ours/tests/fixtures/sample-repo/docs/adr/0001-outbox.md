# ADR-0001: Publish domain events through a transactional outbox

* Status: accepted
* Date: 2026-01-15
* Deciders: @sample/architects

## Context and Problem Statement

Orders must emit `orders.placed` and `orders.paid` exactly once even when the broker is down.

## Decision Outcome

Chosen option: "transactional outbox", because the event row is written in the same transaction as the
order and a relay publishes it afterwards.

## Consequences

* Good: no dual-write anomaly.
* Bad: at-least-once delivery; consumers must be idempotent.
