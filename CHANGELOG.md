# Changelog

## 1.1.0 — 2026-08-30

### Added
- **#33** Persistent Jobs + Scheduling (`JobScheduler`, `JobRecord`, stores, retries, recurrence)
- **#34** Layered Memory + Agent Loadout (`LayeredMemoryManager`, L0–L3, ACL bindings)
- **#35** Yasin-AI capability contract (`CapabilityClient`, mock provider, execution association)
- **#36** Research / information-access boundary (`ResearchClient`, mock provider, ACL)
- **#41** HTTP `POST /v1/executions` create endpoint + E2E orchestration tests
- **#42** Observability helpers (`RuntimeMetrics`, correlation context, `/v1/ready`)
- **#43** Security regression tests (auth, redaction, ACL, isolation)
- **#44** Packaging/docs refresh for production readiness

### Verified
- #32 Durable execution / recovery (17 tests)
- Full suite: 177+ tests green
- Python 3.9–3.13 compatible design (no 3.10+ only syntax in core paths)

### Notes
- Core runtime remains usable without FastAPI, Yasin-AI, or network research providers.
- Secrets are redacted in persistence snapshots and log extras.
