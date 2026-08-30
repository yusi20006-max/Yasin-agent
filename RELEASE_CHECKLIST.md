# Yasin-Agent v1.1.0 — Release Checklist

## Packaging

- [x] Clean clone installs with `pip install -e ".[test-server]"`
- [x] `requires-python = ">=3.9"`
- [x] Core deps do not require FastAPI
- [x] Optional `server` extra installs FastAPI + Uvicorn
- [x] Version from `agent_platform.__version__` (1.1.0)
- [x] Entry point `yasin-agent-server`

## Tests / CI

- [x] CI matrix: Python 3.9–3.13 (`.github/workflows/ci.yml`)
- [x] Core + server + integration tests
- [x] No personal machine paths in tests
- [x] No personal secrets required
- [x] Full suite green locally (200+ tests with server extras)

## Features verified

- [x] #32 Durable execution / recovery
- [x] #33 Persistent jobs + scheduling + bounded concurrency
- [x] #34 Layered memory + agent loadout ACL
- [x] #35 Yasin-AI capability contract (mock)
- [x] #36 Research boundary (mock)
- [x] #41 Hub ↔ Agent E2E (create, lifecycle, fleets, restart recover)
- [x] #42 Observability (metrics, diagnostics, health/ready)
- [x] #43 Security (auth, validation, isolation, redaction)

## Documentation

- [x] README: install, config, server, Hub, persistence, jobs, memory, AI, research
- [x] docs/* for each major subsystem
- [x] SECURITY.md / OBSERVABILITY.md / HUB_AGENT_E2E.md
- [x] CHANGELOG.md

## Security

- [x] No secrets in repository
- [x] Token via environment
- [x] Redaction on events/persistence
- [x] Path-safe stores

## Smoke

```bash
pip install -e ".[test-server]"
pytest tests/ -q
export YASIN_AGENT_SERVICE_TOKEN=dev-token
python -c "from agent_platform.server.app import create_app; create_app(service_token='dev-token'); print('server ok')"
```

## Final

- [x] Architecture audit complete for v1.1.0 production readiness
