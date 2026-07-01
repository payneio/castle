"""Resolve launchable agents for the dashboard terminal UX.

Config (a `castle.yaml` `agents:` block) declares agents; this layer adds the
runtime view: is the binary present, and what's the absolute cwd. Castle stays
agnostic — it only ever runs `command args` in a pty.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from castle_core.config import USER_TOOL_PATH_DIRS

from castle_api.config import get_castle_root, get_config

# Zero-config fallback so the feature works out of the box. A castle.yaml
# `agents:` block overrides this entirely.
_DEFAULT_AGENTS: dict[str, dict] = {
    "claude": {
        "command": "claude",
        "description": "Anthropic Claude Code",
        # Bare --resume pops claude's interactive session-history picker (whereas
        # --continue would silently reopen only the most recent conversation).
        "resume_args": ["--resume"],
    },
    "opencode": {
        "command": "opencode",
        "description": "opencode",
        # opencode has no CLI flag to pop a picker, but it lists sessions as JSON
        # and resumes by id — so the dashboard renders the picker itself.
        "sessions": {
            "list_command": ["opencode", "session", "list", "--format", "json"],
            "resume": ["--session", "{id}"],
            "id_field": "id",
            "title_field": "title",
            "time_field": "updated",
        },
    },
    "amplifier": {
        "command": "amplifier",
        "description": "Amplifier",
        # `amplifier resume` is a subcommand that interactively selects a past
        # session (like claude --resume). (`amplifier continue` = most recent.)
        "resume_args": ["resume"],
    },
}

# Extra dirs to look in beyond the process PATH — where user CLIs actually live.
# opencode installs to ~/.opencode/bin, which the systemd service PATH omits.
_EXTRA_PATH_DIRS = [
    *USER_TOOL_PATH_DIRS,
    Path.home() / ".opencode" / "bin",
]


def _augmented_path() -> str:
    extra = [str(d) for d in _EXTRA_PATH_DIRS if d.exists()]
    current = os.environ.get("PATH", "")
    return os.pathsep.join([*extra, current]) if extra else current


@dataclass
class ResolvedAgent:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    cwd: str = ""
    env: dict[str, str] = field(default_factory=dict)
    description: str | None = None
    resume_args: list[str] = field(default_factory=list)
    sessions: dict | None = None  # SessionsSpec-shaped, or None
    resolved_command: str | None = None  # absolute path if found on PATH

    @property
    def available(self) -> bool:
        return self.resolved_command is not None

    @property
    def can_continue(self) -> bool:
        return bool(self.resume_args)

    @property
    def can_list_sessions(self) -> bool:
        return bool(self.sessions and self.sessions.get("list_command"))

    def launch_env(self) -> dict[str, str]:
        """Env overrides for the pty: augmented PATH so the agent's own tool
        lookups (node, etc.) resolve, plus any configured env."""
        return {"PATH": _augmented_path(), **self.env}

    def info(self) -> dict:
        return {
            "name": self.name,
            "command": self.command,
            "available": self.available,
            "cwd": self.cwd,
            "description": self.description,
            "can_continue": self.can_continue,
            "can_list_sessions": self.can_list_sessions,
        }


def _agent_specs() -> dict[str, dict]:
    """Configured agents (as plain dicts), or the built-in defaults."""
    try:
        config = get_config()
    except FileNotFoundError:
        return _DEFAULT_AGENTS
    if config.agents:
        return {n: s.model_dump(exclude_none=True) for n, s in config.agents.items()}
    return _DEFAULT_AGENTS


def default_cwd() -> str:
    """Where agents launch by default: the castle git repo (its CLAUDE.md /
    AGENTS.md and `castle` sources), falling back to the config root, then home."""
    try:
        repo = get_config().repo
        if repo:
            return str(repo)
    except FileNotFoundError:
        pass
    root = get_castle_root()
    return str(root) if root else str(Path.home())


def _resolve(name: str, spec: dict) -> ResolvedAgent:
    command = spec["command"]
    cwd = spec.get("cwd") or default_cwd()
    resolved = shutil.which(command, path=_augmented_path())
    return ResolvedAgent(
        name=name,
        command=command,
        args=list(spec.get("args") or []),
        cwd=cwd,
        env=dict(spec.get("env") or {}),
        description=spec.get("description"),
        resume_args=list(spec.get("resume_args") or []),
        sessions=spec.get("sessions"),
        resolved_command=resolved,
    )


def list_agents() -> list[ResolvedAgent]:
    return [_resolve(name, spec) for name, spec in _agent_specs().items()]


def resolve_agent(name: str) -> ResolvedAgent | None:
    specs = _agent_specs()
    spec = specs.get(name)
    if spec is None:
        return None
    return _resolve(name, spec)


def _dig(obj: object, path: str) -> object:
    """Read a (possibly dotted) field path off a nested dict, else None."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def resume_argv(agent: ResolvedAgent, session_id: str) -> list[str] | None:
    """Build the argv that resumes a specific past session by id, or None."""
    if not agent.sessions:
        return None
    template = agent.sessions.get("resume") or []
    if not template:
        return None
    base = agent.resolved_command or agent.command
    return [base, *(part.replace("{id}", session_id) for part in template)]


async def list_agent_history(agent: ResolvedAgent, limit: int = 40) -> list[dict]:
    """Run the agent's declared list_command and normalize it to
    [{id, title, time}] — newest first. Best-effort: any failure yields []."""
    if not agent.can_list_sessions:
        return []
    assert agent.sessions is not None
    argv = agent.sessions["list_command"]
    env = {**os.environ, "PATH": _augmented_path()}
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=agent.cwd or None,
            env=env,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
    except (OSError, asyncio.TimeoutError):
        return []
    try:
        data = json.loads(out.decode() or "[]")
    except json.JSONDecodeError:
        return []
    items = (
        data
        if isinstance(data, list)
        else (data.get("sessions") or data.get("data") or [])
    )
    id_f = agent.sessions.get("id_field", "id")
    title_f = agent.sessions.get("title_field", "title")
    time_f = agent.sessions.get("time_field", "updated")
    out_rows: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        sid = _dig(item, id_f)
        if not sid:
            continue
        out_rows.append(
            {
                "agent": agent.name,
                "id": str(sid),
                "title": str(_dig(item, title_f) or ""),
                "time": _dig(item, time_f),
            }
        )
    # Newest first when the time field is sortable; keep input order otherwise.
    try:
        out_rows.sort(key=lambda r: r["time"] or 0, reverse=True)
    except TypeError:
        pass
    return out_rows[:limit]
