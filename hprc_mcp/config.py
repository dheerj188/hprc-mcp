"""Settings for the server, read from config/hprc_mcp.toml (all keys optional)."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_SAFE_REMOTE = re.compile(r"^[A-Za-z0-9._+-]+(/[A-Za-z0-9._+-]+)*$")


@dataclass
class SyncPair:
    """A folder pair the AI may keep in sync. It can trigger a sync but never choose the paths."""

    local: Path
    remote: str  # relative to $SCRATCH on the cluster
    direction: str = "push"  # push = laptop -> cluster, pull = cluster -> laptop
    exclude: list[str] = field(default_factory=lambda: [".git", ".venv", "__pycache__", ".DS_Store"])


def _sync_pair(name: str, raw: dict) -> SyncPair:
    remote = str(raw["remote"]).rstrip("/")
    if not _SAFE_REMOTE.match(remote) or ".." in remote.split("/"):
        raise ValueError(f"sync.{name}.remote must be a plain path under $SCRATCH, got {remote!r}")
    direction = raw.get("direction", "push")
    if direction not in ("push", "pull"):
        raise ValueError(f"sync.{name}.direction must be 'push' or 'pull'")
    local = Path(raw["local"]).expanduser()
    pair = SyncPair(local if local.is_absolute() else (REPO / local).resolve(), remote, direction)
    if "exclude" in raw:
        pair.exclude = list(raw["exclude"])
    return pair


@dataclass
class Config:
    cluster_name: str = "Grace"
    host: str = "grace"  # an alias from ~/.ssh/config
    control_path: str = "~/.ssh/cm-%C"  # must match ControlPath for the host in ~/.ssh/config
    jobs_dir: str = "mcp_jobs"  # under $SCRATCH on the cluster
    partitions: list[str] = field(default_factory=lambda: ["short"])  # empty = any partition
    max_minutes: int = 60
    max_nodes: int = 1
    max_gpus: int = 1
    allow_any_commands: bool = False  # True lifts the job-script command allow-list (own use only)
    upload_dir: Path = REPO / "examples"  # the only local folder the AI may copy files from
    syncs: dict[str, SyncPair] = field(default_factory=dict)


def load_config() -> Config:
    path = Path(os.environ.get("HPRC_MCP_CONFIG", REPO / "config" / "hprc_mcp.toml"))
    if not path.exists():
        return Config()
    raw = tomllib.loads(path.read_text())
    cluster, limits, local = raw.get("cluster", {}), raw.get("limits", {}), raw.get("local", {})
    config = Config(
        cluster_name=cluster.get("name", Config.cluster_name),
        host=cluster.get("host", Config.host),
        control_path=cluster.get("control_path", Config.control_path),
        jobs_dir=cluster.get("jobs_dir", Config.jobs_dir),
        max_minutes=limits.get("max_minutes", Config.max_minutes),
        max_nodes=limits.get("max_nodes", Config.max_nodes),
        max_gpus=limits.get("max_gpus", Config.max_gpus),
        allow_any_commands=raw.get("safety", {}).get("allow_any_commands", False),
    )
    if "partitions" in limits:
        config.partitions = list(limits["partitions"])
    if "upload_dir" in local:
        config.upload_dir = (REPO / local["upload_dir"]).resolve()
    config.syncs = {name: _sync_pair(name, pair) for name, pair in raw.get("sync", {}).items()}
    return config
