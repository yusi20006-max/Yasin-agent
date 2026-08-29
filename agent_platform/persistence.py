"""
persistence.py — Durable execution storage contracts (Issue #32).

Provider-agnostic persistence for ExecutionRecord lifecycle state and
checkpoints. Default remains in-memory (no external dependency). A simple
JSON-file store is provided for local durable tests and single-process recovery.

No credentials or secrets are stored. Callers must pass already-redacted
payloads (ExecutionRecord.as_dict / checkpoint data).
"""

from __future__ import annotations

import json
import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional


class ExecutionStore(ABC):
    """Pluggable persistence for durable executions."""

    @abstractmethod
    def save(self, execution_id: str, payload: Dict[str, Any]) -> None:
        """Upsert a full serializable execution snapshot."""

    @abstractmethod
    def load(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Return snapshot or None if unknown."""

    @abstractmethod
    def delete(self, execution_id: str) -> None:
        """Remove snapshot if present."""

    @abstractmethod
    def list_ids(self) -> List[str]:
        """All known execution_ids."""

    def list_payloads(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for eid in self.list_ids():
            payload = self.load(eid)
            if payload is not None:
                out.append(payload)
        return out


class InMemoryExecutionStore(ExecutionStore):
    """Process-local store. Equivalent to the historical pure in-memory runtime."""

    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def save(self, execution_id: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._data[execution_id] = dict(payload)

    def load(self, execution_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = self._data.get(execution_id)
            return dict(item) if item is not None else None

    def delete(self, execution_id: str) -> None:
        with self._lock:
            self._data.pop(execution_id, None)

    def list_ids(self) -> List[str]:
        with self._lock:
            return list(self._data.keys())

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class JsonFileExecutionStore(ExecutionStore):
    """
    Directory of one JSON file per execution_id.

    Suitable for tests and single-node recovery. Not a multi-writer database.
    Filenames are sanitized; path is never derived from untrusted path input
    beyond the configured root.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, execution_id: str) -> Path:
        # Keep filename safe and stable; execution_id is already opaque.
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in execution_id)
        if not safe:
            safe = "unknown"
        return self.root / f"{safe}.json"

    def save(self, execution_id: str, payload: Dict[str, Any]) -> None:
        path = self._path(execution_id)
        tmp = path.with_suffix(".json.tmp")
        data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        with self._lock:
            tmp.write_text(data, encoding="utf-8")
            os.replace(tmp, path)

    def load(self, execution_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(execution_id)
        with self._lock:
            if not path.is_file():
                return None
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None

    def delete(self, execution_id: str) -> None:
        path = self._path(execution_id)
        with self._lock:
            if path.is_file():
                path.unlink()

    def list_ids(self) -> List[str]:
        with self._lock:
            ids: List[str] = []
            for path in self.root.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    eid = data.get("execution_id")
                    if eid:
                        ids.append(str(eid))
                except (json.JSONDecodeError, OSError):
                    continue
            return ids


__all__ = [
    "ExecutionStore",
    "InMemoryExecutionStore",
    "JsonFileExecutionStore",
]
