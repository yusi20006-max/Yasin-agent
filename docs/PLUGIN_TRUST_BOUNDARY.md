# Plugin trust boundary

Yasin-Agent's plugin mechanism is a local trusted-code extension point.

Plugin code is executable Python and runs with the same operating-system privileges as the Yasin-Agent process. A plugin directory must therefore be treated as a trusted-code location.

This mechanism is not intended to accept untrusted source code from remote users or network requests. Deployments must prevent lower-trust processes or users from writing plugin files into any configured plugin location.

An attacker who can write a plugin file can cause arbitrary Python code to execute when the plugin is loaded. This is a local filesystem trust-boundary condition, not a remote unauthenticated code-execution vulnerability.

The supported plugin mechanism is intentionally retained. This document makes the trust boundary explicit rather than removing or redesigning plugin loading.

## Operational requirements

- Keep plugin directories owned and writable only by the Yasin-Agent operator/service account.
- Do not place downloaded or otherwise untrusted Python files into a plugin directory.
- Treat plugin directory configuration as security-sensitive configuration.
- Review plugin contents as code before enabling them.
