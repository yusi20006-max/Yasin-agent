# Security Hardening & Runtime Isolation (Issue #43)

## Authentication

- Service-to-service: `Authorization: Bearer <token>`
- Token from `YASIN_AGENT_SERVICE_TOKEN` (never committed)
- Comparison via `secrets.compare_digest`

## Authorization / isolation

- Execution capabilities are explicit; research/AI require capability grants
- Agent Loadout ACL prevents cross-agent memory access
- Cancel/pause only affect the targeted execution_id
- Session/agent isolation helpers available for higher layers

## Input validation

- Identifiers: alphanumeric + `._-`, max 128, no path traversal
- Capabilities: lowercase slug form
- Metadata size bounds
- Request body size limit (~1 MiB)

## Secrets

- `redact_secrets` on events, persistence, diagnostics, logs
- No secrets in repository source

## Network / research

- No unrestricted network from agents
- Research is an explicit capability with replaceable providers

## Deployment

```bash
export YASIN_AGENT_SERVICE_TOKEN="$(openssl rand -hex 32)"
python -m agent_platform.server
```

Do not log the token. Rotate periodically. Use TLS at the edge in production.
