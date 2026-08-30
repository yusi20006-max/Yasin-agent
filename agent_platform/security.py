"""
security.py — Security hardening helpers (Issue #43).

Input validation, identifier hygiene, safe errors, and isolation checks.
No secrets in logs; service auth remains in the HTTP layer.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Sequence

# Opaque IDs: alphanumeric, dash, underscore; bounded length.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$")
_PATH_TRAVERSAL = re.compile(r"(?:\.\./|\.\.\\)")

# Capabilities that must never be implied by scheduling/jobs alone.
DANGEROUS_CAPABILITIES = frozenset(
    {
        "shell",
        "subprocess",
        "computer_use",
        "browser",
        "unrestricted_network",
        "fs_write_root",
    }
)

MAX_JSON_BODY_BYTES = 1_048_576  # 1 MiB
MAX_METADATA_KEYS = 64
MAX_METADATA_STRING = 8_192


class SecurityError(ValueError):
    """Raised when a security validation fails (safe message only)."""


def validate_identifier(value: Optional[str], *, name: str = "id") -> str:
    if value is None or not isinstance(value, str) or not value.strip():
        raise SecurityError(f"invalid {name}")
    value = value.strip()
    if not _ID_RE.match(value):
        raise SecurityError(f"invalid {name}")
    if _PATH_TRAVERSAL.search(value):
        raise SecurityError(f"invalid {name}")
    return value


def validate_optional_identifier(value: Optional[str], *, name: str = "id") -> Optional[str]:
    if value is None or value == "":
        return None
    return validate_identifier(value, name=name)


def sanitize_metadata(metadata: Optional[dict]) -> dict:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise SecurityError("metadata must be an object")
    if len(metadata) > MAX_METADATA_KEYS:
        raise SecurityError("metadata too large")
    out = {}
    for i, (k, v) in enumerate(metadata.items()):
        if i >= MAX_METADATA_KEYS:
            break
        key = str(k)[:128]
        if isinstance(v, str) and len(v) > MAX_METADATA_STRING:
            v = v[:MAX_METADATA_STRING]
        out[key] = v
    return out


def validate_capabilities(capabilities: Optional[Sequence[str]]) -> list:
    if capabilities is None:
        return []
    if not isinstance(capabilities, (list, tuple, set)):
        raise SecurityError("capabilities must be a list")
    out = []
    for c in capabilities:
        if not isinstance(c, str) or not c.strip():
            raise SecurityError("invalid capability")
        name = c.strip()
        if len(name) > 64 or not re.match(r"^[a-z][a-z0-9_\-]{0,63}$", name):
            raise SecurityError("invalid capability")
        out.append(name)
    return out


def reject_dangerous_capabilities(capabilities: Sequence[str]) -> None:
    """Optional policy: block known dangerous caps unless explicitly allowed later."""
    bad = DANGEROUS_CAPABILITIES.intersection(capabilities)
    if bad:
        raise SecurityError(f"capability not permitted: {sorted(bad)[0]}")


def safe_error_detail(exc: BaseException, *, public: str = "request failed") -> str:
    """Map internal exceptions to non-leaky client messages when needed."""
    if isinstance(exc, SecurityError):
        return str(exc)
    msg = str(exc)
    # Avoid leaking filesystem paths / tokens from unexpected errors.
    if "/home/" in msg or "/Users/" in msg or "Traceback" in msg:
        return public
    if len(msg) > 500:
        return public
    return msg or public


def assert_same_session(record_session: Optional[str], requested: Optional[str]) -> None:
    if requested is None:
        return
    if record_session != requested:
        raise SecurityError("session isolation violation")


def assert_same_agent(record_agent: Optional[str], requested: Optional[str]) -> None:
    if requested is None:
        return
    if record_agent != requested:
        raise SecurityError("agent isolation violation")


def is_safe_workspace_path(path: Optional[str], *, allowed_roots: Optional[Sequence[str]] = None) -> bool:
    if path is None or path == "":
        return True
    if _PATH_TRAVERSAL.search(path):
        return False
    if path.startswith("~") or path.startswith("//"):
        return False
    if allowed_roots:
        return any(path == root or path.startswith(root.rstrip("/") + "/") for root in allowed_roots)
    # Without configured roots, reject absolute paths outside tmp-like prefixes.
    if path.startswith("/") and not (
        path.startswith("/tmp") or path.startswith("/var/tmp") or path.startswith("/workspace")
    ):
        return False
    return True


__all__ = [
    "SecurityError",
    "DANGEROUS_CAPABILITIES",
    "MAX_JSON_BODY_BYTES",
    "validate_identifier",
    "validate_optional_identifier",
    "sanitize_metadata",
    "validate_capabilities",
    "reject_dangerous_capabilities",
    "safe_error_detail",
    "assert_same_session",
    "assert_same_agent",
    "is_safe_workspace_path",
]
