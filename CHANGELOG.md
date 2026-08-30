# Changelog

## 1.1.0 — 2026-08-30

Production-ready execution runtime integrated with YasinHub.

### Added
- **#33** Persistent Jobs + Scheduling (`JobScheduler`, retry, recurrence, `max_concurrent`)
- **#34** Layered Memory + Agent Loadout (L0–L3, ACL, skills)
- **#35** Yasin-AI capability contract (`CapabilityClient`, mock/configurable providers)
- **#36** Research information-access boundary (`ResearchClient`, registry, ToolRunner hook)
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
