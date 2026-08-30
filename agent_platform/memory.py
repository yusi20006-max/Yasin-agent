"""
memory.py — Layered memory + Agent Loadout (Issue #34).

Layers (conceptual):
  L0 Conversation  — short-lived turn/session dialogue
  L1 Atom          — atomic facts / notes
  L2 Scenario      — scenario / episode bindings
  L3 Core / Persona — stable persona / long-term identity

Memory is separate from Skill. Both are addressable as runtime assets.
Agent Loadout explicitly determines what an agent may access (memory,
skills, wiki, codegraph, capabilities). No automatic global memory grant.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from .execution import redact_secrets


class MemoryLayer(str, Enum):
    L0_CONVERSATION = "L0"
    L1_ATOM = "L1"
    L2_SCENARIO = "L2"
    L3_CORE = "L3"


class AssetType(str, Enum):
    MEMORY = "memory"
    SKILL = "skill"
    WIKI = "wiki"
    CODEGRAPH = "codegraph"
    CAPABILITY = "capability"


@dataclass
class MemoryAsset:
    """Versionable memory asset with stable id and metadata."""

    asset_id: str
    layer: MemoryLayer
    content: Any
    version: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    owner_agent_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return redact_secrets(
            {
                "asset_id": self.asset_id,
                "layer": self.layer.value if isinstance(self.layer, MemoryLayer) else self.layer,
                "content": self.content,
                "version": self.version,
                "metadata": dict(self.metadata),
                "tags": list(self.tags),
                "owner_agent_id": self.owner_agent_id,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryAsset":
        layer = data.get("layer", MemoryLayer.L1_ATOM.value)
        if isinstance(layer, str):
            layer = MemoryLayer(layer)
        return cls(
            asset_id=str(data["asset_id"]),
            layer=layer,
            content=data.get("content"),
            version=int(data.get("version") or 1),
            metadata=dict(data.get("metadata") or {}),
            tags=list(data.get("tags") or []),
            owner_agent_id=data.get("owner_agent_id"),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
        )


@dataclass
class LoadoutBinding:
    """ACL-style binding of an asset to an agent/loadout."""

    asset_id: str
    asset_type: AssetType
    allow_read: bool = True
    allow_write: bool = False
    scope: Optional[str] = None  # optional session/workspace scope

    def as_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type.value
            if isinstance(self.asset_type, AssetType)
            else self.asset_type,
            "allow_read": self.allow_read,
            "allow_write": self.allow_write,
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoadoutBinding":
        at = data.get("asset_type", AssetType.MEMORY.value)
        if isinstance(at, str):
            at = AssetType(at)
        return cls(
            asset_id=str(data["asset_id"]),
            asset_type=at,
            allow_read=bool(data.get("allow_read", True)),
            allow_write=bool(data.get("allow_write", False)),
            scope=data.get("scope"),
        )


@dataclass
class AgentLoadout:
    """
    Explicit set of assets an agent may access.

    Agents do not automatically receive every memory; the loadout must
    bind them.
    """

    loadout_id: str
    agent_id: str
    bindings: List[LoadoutBinding] = field(default_factory=list)
    capabilities: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: int = 1
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if isinstance(self.capabilities, (list, tuple)):
            self.capabilities = set(self.capabilities)
        normalized: List[LoadoutBinding] = []
        for b in self.bindings:
            if isinstance(b, dict):
                normalized.append(LoadoutBinding.from_dict(b))
            else:
                normalized.append(b)
        self.bindings = normalized

    def allows(
        self,
        asset_id: str,
        *,
        asset_type: AssetType = AssetType.MEMORY,
        write: bool = False,
        scope: Optional[str] = None,
    ) -> bool:
        for b in self.bindings:
            if b.asset_id != asset_id:
                continue
            if b.asset_type != asset_type and b.asset_type != AssetType(asset_type):
                continue
            if scope is not None and b.scope is not None and b.scope != scope:
                continue
            if write:
                return b.allow_write
            return b.allow_read
        return False

    def allows_capability(self, capability: str) -> bool:
        return capability in self.capabilities

    def as_dict(self) -> Dict[str, Any]:
        return redact_secrets(
            {
                "loadout_id": self.loadout_id,
                "agent_id": self.agent_id,
                "bindings": [b.as_dict() for b in self.bindings],
                "capabilities": sorted(self.capabilities),
                "metadata": dict(self.metadata),
                "version": self.version,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentLoadout":
        return cls(
            loadout_id=str(data["loadout_id"]),
            agent_id=str(data["agent_id"]),
            bindings=[LoadoutBinding.from_dict(b) for b in (data.get("bindings") or [])],
            capabilities=set(data.get("capabilities") or []),
            metadata=dict(data.get("metadata") or {}),
            version=int(data.get("version") or 1),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
        )


class MemoryAccessDenied(PermissionError):
    """Raised when loadout ACL denies memory/asset access."""

    def __init__(self, agent_id: str, asset_id: str, action: str = "read") -> None:
        self.agent_id = agent_id
        self.asset_id = asset_id
        self.action = action
        super().__init__(
            f"agent {agent_id} denied {action} on asset {asset_id}"
        )


class MemoryStore:
    def save_asset(self, asset_id: str, payload: Dict[str, Any]) -> None:
        raise NotImplementedError

    def load_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def delete_asset(self, asset_id: str) -> None:
        raise NotImplementedError

    def list_asset_ids(self) -> List[str]:
        raise NotImplementedError

    def save_loadout(self, loadout_id: str, payload: Dict[str, Any]) -> None:
        raise NotImplementedError

    def load_loadout(self, loadout_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def delete_loadout(self, loadout_id: str) -> None:
        raise NotImplementedError

    def list_loadout_ids(self) -> List[str]:
        raise NotImplementedError


class InMemoryMemoryStore(MemoryStore):
    def __init__(self) -> None:
        self._assets: Dict[str, Dict[str, Any]] = {}
        self._loadouts: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def save_asset(self, asset_id: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._assets[asset_id] = dict(payload)

    def load_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = self._assets.get(asset_id)
            return dict(item) if item is not None else None

    def delete_asset(self, asset_id: str) -> None:
        with self._lock:
            self._assets.pop(asset_id, None)

    def list_asset_ids(self) -> List[str]:
        with self._lock:
            return list(self._assets.keys())

    def save_loadout(self, loadout_id: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._loadouts[loadout_id] = dict(payload)

    def load_loadout(self, loadout_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = self._loadouts.get(loadout_id)
            return dict(item) if item is not None else None

    def delete_loadout(self, loadout_id: str) -> None:
        with self._lock:
            self._loadouts.pop(loadout_id, None)

    def list_loadout_ids(self) -> List[str]:
        with self._lock:
            return list(self._loadouts.keys())


class JsonFileMemoryStore(MemoryStore):
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.assets_dir = self.root / "assets"
        self.loadouts_dir = self.root / "loadouts"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.loadouts_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _safe(self, name: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        return safe or "unknown"

    def _write(self, path: Path, payload: Dict[str, Any]) -> None:
        tmp = path.with_suffix(".json.tmp")
        data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        with self._lock:
            tmp.write_text(data, encoding="utf-8")
            os.replace(tmp, path)

    def _read(self, path: Path) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not path.is_file():
                return None
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None

    def save_asset(self, asset_id: str, payload: Dict[str, Any]) -> None:
        self._write(self.assets_dir / f"{self._safe(asset_id)}.json", payload)

    def load_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        return self._read(self.assets_dir / f"{self._safe(asset_id)}.json")

    def delete_asset(self, asset_id: str) -> None:
        path = self.assets_dir / f"{self._safe(asset_id)}.json"
        with self._lock:
            if path.is_file():
                path.unlink()

    def list_asset_ids(self) -> List[str]:
        with self._lock:
            ids: List[str] = []
            for path in self.assets_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    aid = data.get("asset_id")
                    if aid:
                        ids.append(str(aid))
                except (json.JSONDecodeError, OSError):
                    continue
            return ids

    def save_loadout(self, loadout_id: str, payload: Dict[str, Any]) -> None:
        self._write(self.loadouts_dir / f"{self._safe(loadout_id)}.json", payload)

    def load_loadout(self, loadout_id: str) -> Optional[Dict[str, Any]]:
        return self._read(self.loadouts_dir / f"{self._safe(loadout_id)}.json")

    def delete_loadout(self, loadout_id: str) -> None:
        path = self.loadouts_dir / f"{self._safe(loadout_id)}.json"
        with self._lock:
            if path.is_file():
                path.unlink()

    def list_loadout_ids(self) -> List[str]:
        with self._lock:
            ids: List[str] = []
            for path in self.loadouts_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    lid = data.get("loadout_id")
                    if lid:
                        ids.append(str(lid))
                except (json.JSONDecodeError, OSError):
                    continue
            return ids


class LayeredMemoryManager:
    """
    Provider-agnostic layered memory with loadout ACL enforcement.

    Integrate with ExecutionRuntime by checking capabilities / loadout
    before memory operations when an agent_id + loadout is active.
    """

    def __init__(self, store: Optional[MemoryStore] = None) -> None:
        self._store: MemoryStore = store or InMemoryMemoryStore()
        self._assets: Dict[str, MemoryAsset] = {}
        self._loadouts: Dict[str, AgentLoadout] = {}
        self._agent_loadout: Dict[str, str] = {}  # agent_id -> loadout_id
        self._lock = threading.RLock()

    # ---- Memory CRUD ----

    def add_memory(
        self,
        content: Any,
        *,
        layer: MemoryLayer = MemoryLayer.L1_ATOM,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[Sequence[str]] = None,
        owner_agent_id: Optional[str] = None,
        asset_id: Optional[str] = None,
    ) -> MemoryAsset:
        asset = MemoryAsset(
            asset_id=asset_id or f"mem-{uuid.uuid4().hex[:16]}",
            layer=layer,
            content=content,
            metadata=dict(metadata or {}),
            tags=list(tags or []),
            owner_agent_id=owner_agent_id,
        )
        with self._lock:
            if asset.asset_id in self._assets:
                raise ValueError(f"asset_id already exists: {asset.asset_id}")
            self._assets[asset.asset_id] = asset
        self._persist_asset(asset)
        return asset

    def update_memory(
        self,
        asset_id: str,
        *,
        content: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[Sequence[str]] = None,
        agent_id: Optional[str] = None,
    ) -> MemoryAsset:
        asset = self._require_asset(asset_id)
        if agent_id is not None:
            self._check_access(agent_id, asset_id, write=True)
        if content is not None:
            asset.content = content
        if metadata is not None:
            asset.metadata.update(metadata)
        if tags is not None:
            asset.tags = list(tags)
        asset.version += 1
        asset.updated_at = time.time()
        self._persist_asset(asset)
        return asset

    def remove_memory(self, asset_id: str, *, agent_id: Optional[str] = None) -> None:
        if agent_id is not None:
            self._check_access(agent_id, asset_id, write=True)
        with self._lock:
            self._assets.pop(asset_id, None)
        try:
            self._store.delete_asset(asset_id)
        except Exception:
            pass

    def get_memory(
        self,
        asset_id: str,
        *,
        agent_id: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> Optional[MemoryAsset]:
        asset = self._assets.get(asset_id)
        if asset is None:
            payload = self._store.load_asset(asset_id)
            if payload is None:
                return None
            asset = MemoryAsset.from_dict(payload)
            with self._lock:
                self._assets[asset_id] = asset
        if agent_id is not None:
            self._check_access(agent_id, asset_id, write=False, scope=scope)
        return asset

    def search_memory(
        self,
        *,
        layer: Optional[MemoryLayer] = None,
        tags: Optional[Sequence[str]] = None,
        query: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[MemoryAsset]:
        """Scoped search. When agent_id is set, only accessible assets are returned."""
        with self._lock:
            items = list(self._assets.values())
        # hydrate missing from store
        for aid in self._store.list_asset_ids():
            if aid not in self._assets:
                payload = self._store.load_asset(aid)
                if payload:
                    try:
                        a = MemoryAsset.from_dict(payload)
                        with self._lock:
                            self._assets[aid] = a
                        items.append(a)
                    except (KeyError, TypeError, ValueError):
                        continue
        results: List[MemoryAsset] = []
        tag_set = set(tags or ())
        for asset in items:
            if layer is not None and asset.layer != layer:
                continue
            if tag_set and not tag_set.intersection(asset.tags):
                continue
            if query is not None:
                blob = json.dumps(asset.content, default=str).lower()
                if query.lower() not in blob and query.lower() not in " ".join(
                    asset.tags
                ).lower():
                    continue
            if agent_id is not None:
                if not self._may_access(agent_id, asset.asset_id, write=False):
                    continue
            results.append(asset)
            if len(results) >= limit:
                break
        return results

    # ---- Loadout ----

    def create_loadout(
        self,
        agent_id: str,
        *,
        bindings: Optional[Sequence[LoadoutBinding]] = None,
        capabilities: Optional[Sequence[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        loadout_id: Optional[str] = None,
        activate: bool = True,
    ) -> AgentLoadout:
        lo = AgentLoadout(
            loadout_id=loadout_id or f"lo-{uuid.uuid4().hex[:16]}",
            agent_id=agent_id,
            bindings=list(bindings or []),
            capabilities=set(capabilities or []),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            if lo.loadout_id in self._loadouts:
                raise ValueError(f"loadout_id already exists: {lo.loadout_id}")
            self._loadouts[lo.loadout_id] = lo
            if activate:
                self._agent_loadout[agent_id] = lo.loadout_id
        self._persist_loadout(lo)
        return lo

    def attach_memory(
        self,
        loadout_id: str,
        asset_id: str,
        *,
        allow_read: bool = True,
        allow_write: bool = False,
        scope: Optional[str] = None,
    ) -> AgentLoadout:
        lo = self._require_loadout(loadout_id)
        # ensure asset exists
        if self.get_memory(asset_id) is None:
            raise KeyError(f"unknown asset_id: {asset_id}")
        # replace existing binding for same asset
        lo.bindings = [b for b in lo.bindings if b.asset_id != asset_id]
        lo.bindings.append(
            LoadoutBinding(
                asset_id=asset_id,
                asset_type=AssetType.MEMORY,
                allow_read=allow_read,
                allow_write=allow_write,
                scope=scope,
            )
        )
        lo.version += 1
        lo.updated_at = time.time()
        self._persist_loadout(lo)
        return lo

    def detach_memory(self, loadout_id: str, asset_id: str) -> AgentLoadout:
        lo = self._require_loadout(loadout_id)
        lo.bindings = [b for b in lo.bindings if b.asset_id != asset_id]
        lo.version += 1
        lo.updated_at = time.time()
        self._persist_loadout(lo)
        return lo

    def load_loadout(self, loadout_id: str) -> Optional[AgentLoadout]:
        lo = self._loadouts.get(loadout_id)
        if lo is not None:
            return lo
        payload = self._store.load_loadout(loadout_id)
        if payload is None:
            return None
        lo = AgentLoadout.from_dict(payload)
        with self._lock:
            self._loadouts[loadout_id] = lo
        return lo

    def activate_loadout(self, agent_id: str, loadout_id: str) -> AgentLoadout:
        lo = self._require_loadout(loadout_id)
        if lo.agent_id != agent_id:
            raise MemoryAccessDenied(agent_id, loadout_id, action="activate")
        with self._lock:
            self._agent_loadout[agent_id] = loadout_id
        return lo

    def get_active_loadout(self, agent_id: str) -> Optional[AgentLoadout]:
        with self._lock:
            lid = self._agent_loadout.get(agent_id)
        if lid is None:
            return None
        return self.load_loadout(lid)

    def validate_loadout(self, loadout_id: str) -> List[str]:
        """Return list of problems (empty if valid)."""
        problems: List[str] = []
        lo = self.load_loadout(loadout_id)
        if lo is None:
            return [f"loadout not found: {loadout_id}"]
        for b in lo.bindings:
            if b.asset_type == AssetType.MEMORY:
                if self.get_memory(b.asset_id) is None:
                    problems.append(f"missing memory asset: {b.asset_id}")
        return problems

    # ---- ACL helpers ----

    def _may_access(
        self,
        agent_id: str,
        asset_id: str,
        *,
        write: bool = False,
        scope: Optional[str] = None,
    ) -> bool:
        lo = self.get_active_loadout(agent_id)
        if lo is None:
            return False
        return lo.allows(
            asset_id, asset_type=AssetType.MEMORY, write=write, scope=scope
        )

    def _check_access(
        self,
        agent_id: str,
        asset_id: str,
        *,
        write: bool = False,
        scope: Optional[str] = None,
    ) -> None:
        if not self._may_access(agent_id, asset_id, write=write, scope=scope):
            raise MemoryAccessDenied(
                agent_id, asset_id, action="write" if write else "read"
            )

    def _require_asset(self, asset_id: str) -> MemoryAsset:
        asset = self.get_memory(asset_id)
        if asset is None:
            raise KeyError(f"unknown asset_id: {asset_id}")
        return asset

    def _require_loadout(self, loadout_id: str) -> AgentLoadout:
        lo = self.load_loadout(loadout_id)
        if lo is None:
            raise KeyError(f"unknown loadout_id: {loadout_id}")
        return lo

    def _persist_asset(self, asset: MemoryAsset) -> None:
        try:
            self._store.save_asset(asset.asset_id, asset.as_dict())
        except Exception:
            pass

    def _persist_loadout(self, lo: AgentLoadout) -> None:
        try:
            self._store.save_loadout(lo.loadout_id, lo.as_dict())
        except Exception:
            pass


__all__ = [
    "MemoryLayer",
    "AssetType",
    "MemoryAsset",
    "LoadoutBinding",
    "AgentLoadout",
    "MemoryAccessDenied",
    "MemoryStore",
    "InMemoryMemoryStore",
    "JsonFileMemoryStore",
    "LayeredMemoryManager",
]
