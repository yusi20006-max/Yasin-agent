# FINAL-G2 — Agent ↔ Yasin-AI Integration Boundary

**Issue:** Yasin-agent #22  
**Related:** #19  
**Date:** 2026-08-16  
**Decision:** **NOT PLANNED** for current architecture

## Evidence

| Check | Result |
|-------|--------|
| Runtime foundation | Yasin-Core public SDK (`yasin_core.sdk`) + in-process mocks |
| `GenerationService` / `yasinai.contracts` call sites | **None** |
| Tests without Yasin-AI | **44 passed** |
| CI | green without Yasin-AI install |
| Dependency direction | Agent → Core only; no Agent → Yasin-AI edge |
| Cycle risk with AI | None (no edge) |

## #19 disposition

**NOT PLANNED** (not merely deferred indefinitely without decision).

Integrating canonical Yasin-AI capability contracts would be a **new product dependency**. No current Agent goal, planner step, or test requires generation/memory from Yasin-AI public contracts.

Re-open only via a **dedicated implementation Issue** that:
1. Names a concrete Agent use case
2. Uses **only** `yasinai.contracts` / `yasinai.services` / `yasinai.providers` (v1.1.4)
3. Forbids `knowledge_platform`, `security_platform`, `developer_platform`, and other private modules
4. Adds tests + boundary CI coverage

## Boundary hygiene in #22

`agent_platform/cli.py` previously attempted optional `import knowledge_platform` / `security_platform` / `developer_platform` (Yasin-AI private package names) with mock fallbacks. Those imports are **removed**. Demo tools now use local in-file stubs only, so accidental coupling to private AI packages cannot occur if those packages are installed on `PYTHONPATH`.

## Acceptance

| Criterion | Status |
|-----------|--------|
| Evidence-backed decision | Met |
| #19 clear disposition | **NOT PLANNED** |
| Docs updated | This file |
| No forced Yasin-AI adoption | Met |
| No private AI imports | Met after cli hygiene |
| No unrelated features | Met |
