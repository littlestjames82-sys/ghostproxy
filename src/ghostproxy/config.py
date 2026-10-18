"""GhostProxy configuration.

Sources, in increasing priority: built-in defaults, the ``proxy`` section
of a project's ``.ghostslice.json`` (same profile file as GhostSlice),
then explicit CLI arguments. Unknown keys in the proxy section fail
loudly (house rule shared with GhostSlice lint/profile behaviour).

Hard rules enforced here, not preferences:
- host must be a loopback literal (127.0.0.1, ::1, or "localhost");
- request bodies are never logged by default: log_bodies is False
  unless explicitly opted into (profile proxy section or serve flag),
  and the v0.1 ledger schema contains no body field in any case.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_UPSTREAM = "https://api.anthropic.com"
DEFAULT_BUDGET_TOKENS = 60_000
DEFAULT_UPSTREAM_TIMEOUT = 120.0
DEFAULT_MAX_BODY_BYTES = 4 * 1024 * 1024  # larger requests pass through untouched
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")

_PROFILE_KEYS = {
    "host", "port", "upstream", "budget_tokens", "enabled",
    "upstream_timeout", "max_body_bytes", "ledger", "log_bodies",
}
_CLI_KEYS = {"host", "port", "upstream", "budget_tokens", "project",
             "ledger_path", "ghostslice_project", "enabled",
             "upstream_timeout", "max_body_bytes", "log_bodies"}


class ConfigError(ValueError):
    pass


@dataclass
class ProxyConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    upstream: str = DEFAULT_UPSTREAM
    budget_tokens: int = DEFAULT_BUDGET_TOKENS
    project: str = ""                 # project label recorded in the ledger
    ghostslice_project: str = ""      # project dir whose .ghostslice.json is read
    ledger_path: str = ""             # default: <cwd>/.ghostproxy-ledger.jsonl
    enabled: bool = True              # per-project on/off from the profile
    upstream_timeout: float = DEFAULT_UPSTREAM_TIMEOUT
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    log_bodies: bool = False          # explicit opt-in only; see module docstring

    def __post_init__(self):
        if self.host not in LOOPBACK_HOSTS:
            raise ConfigError(
                f"refusing to bind non-loopback host {self.host!r}: "
                "GhostProxy v0.1 is localhost only (127.0.0.1)")
        # Normalise "localhost" to the literal so binding is unambiguous.
        if self.host == "localhost":
            self.host = "127.0.0.1"
        try:
            port_int = int(self.port)
            budget_int = int(self.budget_tokens)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"port and budget_tokens must be numbers "
                f"(got port={self.port!r}, budget_tokens={self.budget_tokens!r})"
            ) from exc
        if not (0 <= port_int <= 65535):  # 0 = OS-assigned (tests)
            raise ConfigError(f"invalid port: {self.port!r}")
        if budget_int < 0:
            raise ConfigError("budget_tokens must be >= 0")
        if not (self.upstream.startswith("http://")
                or self.upstream.startswith("https://")):
            raise ConfigError(f"upstream must be an http(s) URL: {self.upstream!r}")
        self.port = int(self.port)
        self.budget_tokens = int(self.budget_tokens)

    def ledger_file(self) -> Path:
        if self.ledger_path:
            return Path(self.ledger_path)
        # Per-project ledger next to the project when one is known (this is
        # what `ghostproxy report --project <dir>` reads back).
        for cand in (self.ghostslice_project, self.project):
            if cand and Path(cand).is_dir():
                return Path(cand) / ".ghostproxy-ledger.jsonl"
        return Path.cwd() / ".ghostproxy-ledger.jsonl"


def load_profile_proxy_section(project_dir: str | Path) -> dict:
    """Read the ``proxy`` section of <project>/.ghostslice.json.

    Returns {} when the file or section is absent. Raises ConfigError on
    malformed JSON or unknown proxy keys (fail loudly, per plan).
    """
    profile = Path(project_dir) / ".ghostslice.json"
    if not profile.is_file():
        return {}
    try:
        data = json.loads(profile.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConfigError(f"cannot parse {profile}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{profile}: top level must be an object")
    section = data.get("proxy", {})
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ConfigError(f"{profile}: 'proxy' section must be an object")
    unknown = sorted(set(section) - _PROFILE_KEYS)
    if unknown:
        raise ConfigError(
            f"{profile}: unknown proxy keys: {', '.join(unknown)}")
    out = dict(section)
    if "ledger" in out:
        out["ledger_path"] = out.pop("ledger")
    return out


def build_config(project_dir: str | Path | None = None,
                 overrides: dict | None = None) -> ProxyConfig:
    """Defaults <- profile proxy section <- explicit overrides."""
    values: dict = {}
    if project_dir:
        values.update(load_profile_proxy_section(project_dir))
        values.setdefault("ghostslice_project", str(project_dir))
        values.setdefault("project", str(project_dir))
    for key, val in (overrides or {}).items():
        if val is None:
            continue
        if key not in _CLI_KEYS:
            raise ConfigError(f"unknown config override: {key}")
        values[key] = val
    # log_bodies defaults off; turning it on requires an explicit
    # log_bodies: true in the profile proxy section or the serve flag.
    # (The v0.1 ledger schema has no body field regardless.)
    values.setdefault("log_bodies", False)
    return ProxyConfig(**values)
