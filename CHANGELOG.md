# Changelog

## 1.1.1 — Phase 6 production hardening (2026-09-04)

### Added
- Phase 6 regression suite (`tests/test_phase6_production_hardening.py`)
- Concurrent Idempotency-Key safety on `POST /v1/executions`
- Stale `.json.tmp` cleanup during durable store recovery listing

### Hardened
- Create-path idempotency is atomic under a single lock (no double-create race)
- Corrupt JSON snapshots continue to return `None` without crashing recovery

### Verified
- Full suite green (Phase 5 + Phase 6)
- No second control plane / PID authority in Agent
- Packaging entrypoint and Python >=3.9 metadata intact
- Physical Termux/Android acceptance remains deferred

## 1.1.0

### Added / completed
- **#33** Persistent jobs + scheduling primitives
- **#34** Layered memory + agent loadout contracts
- **#35** Yasin-AI capability contract boundary
- **#36** Research/information-access boundary (`ResearchClient`, registry, ToolRunner hook)
- **#41** Hub ↔ Agent E2E (`POST /v1/executions`, durable recover on GET/control, `HubAgentClient`)
- **#42** Observability (`RuntimeMetrics`, `/v1/metrics`, diagnostics, health with metrics)
- **#43** Security hardening (`security.py`, validation, body limits, isolation tests)
- **#44** Packaging, README, release checklist for 1.1.0

### Verified
- **#32** Durable execution / recovery
- CI matrix Python 3.9–3.13
- Core runtime usable without server/AI/research providers

### Security
- Bearer auth with constant-time compare
- Secret redaction in events, snapshots, diagnostics
- No secrets in repository

## 1.0.0

Initial stable surface: execution runtime, HTTP adapter (#38), fleets, harness.
