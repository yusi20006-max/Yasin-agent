# Research / Information-Access Boundary (Issue #36)

Research is an **explicit capability**, not unrestricted network access.

## Contract

```text
ResearchRequest  →  ResearchProvider.search  →  ResearchResult
```

- Sources carry url, title, snippet, published_at, confidence, metadata
- Provenance, timestamps, execution/session/worker correlation
- Secrets redacted in `as_dict()`

## Bounds

| Limit | Default | Hard max |
|-------|---------|----------|
| max_results | 5 | 50 |
| timeout_seconds | 15 | 120 |
| max_retries | 1 | (client config) |

## Providers

`ResearchRegistry` + `ResearchClient.register_provider(name, provider)`.

Default: `MockResearchProvider` (no network, no credentials).

## ToolRunner

```python
client.register_on_tool_runner(tool_runner, name="research")
```

Existing tools remain unchanged.

## Governance

- Requires execution capability `"research"` when bound to `ExecutionRuntime`
- Events: `research.search`
- Yasin-MCP remains authoritative for tool authorization outside this boundary
