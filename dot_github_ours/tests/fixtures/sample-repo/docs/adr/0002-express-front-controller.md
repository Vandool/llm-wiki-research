# ADR-0002: Keep a thin Express front controller

* Status: proposed
* Date: 2026-03-02

## Context and Problem Statement

The web layer only validates and forwards; business rules stay in Python.

## Decision Outcome

Chosen option: "thin controller", validation via zod, no business logic in TypeScript.
