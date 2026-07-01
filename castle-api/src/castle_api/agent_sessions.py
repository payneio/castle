"""Live agent/terminal session registry.

A session is a running PTY (an agent CLI or a shell) whose lifetime is decoupled
from any WebSocket connection: closing the browser tab detaches, it does not
kill the process. Sessions can be listed, re-attached (resumed) by id, and
explicitly terminated. Each session keeps a bounded scrollback buffer so a
re-attaching client can repaint the terminal.

This is deliberately in-memory and single-node: sessions do not survive a
castle-api restart. That's the right scope for a personal dashboard — for true
cross-restart persistence you'd launch the agent under tmux, which breaks the
"castle just runs a command" agnosticism.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from castle_api.pty_session import PtySession

# Cap the per-session replay buffer. Raw terminal bytes; enough to repaint a
# full-screen TUI and some history without unbounded growth.
_SCROLLBACK_BYTES = 256 * 1024
# Reap sessions that have exited and sat idle longer than this (seconds).
_EXITED_TTL = 3600


@dataclass
class AgentSession:
    """One live PTY plus its scrollback and attached subscribers."""

    id: str
    agent: str  # agent name, or "terminal" for the plain shell
    command: str
    cwd: str
    created_at: float
    pty: PtySession | None = None
    scrollback: bytearray = field(default_factory=bytearray)
    subscribers: set[asyncio.Queue[bytes | None]] = field(default_factory=set)
    exited: bool = False
    exit_code: int | None = None
    exited_at: float | None = None

    def _on_output(self, data: bytes) -> None:
        self.scrollback.extend(data)
        if len(self.scrollback) > _SCROLLBACK_BYTES:
            del self.scrollback[: len(self.scrollback) - _SCROLLBACK_BYTES]
        for q in list(self.subscribers):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                # Slow client: drop it; the WS side will notice on its next send.
                self.subscribers.discard(q)

    def _on_exit(self) -> None:
        self.exited = True
        self.exit_code = self.pty.proc.returncode if self.pty else None
        self.exited_at = time.time()
        for q in list(self.subscribers):
            q.put_nowait(None)  # EOF sentinel

    def subscribe(self) -> asyncio.Queue[bytes | None]:
        q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=256)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[bytes | None]) -> None:
        self.subscribers.discard(q)

    @property
    def running(self) -> bool:
        return not self.exited and self.pty is not None and self.pty.running

    def info(self) -> dict:
        return {
            "id": self.id,
            "agent": self.agent,
            "command": self.command,
            "cwd": self.cwd,
            "created_at": self.created_at,
            "running": self.running,
            "exited": self.exited,
            "exit_code": self.exit_code,
            "cols": self.pty.cols if self.pty else None,
            "rows": self.pty.rows if self.pty else None,
            "clients": len(self.subscribers),
        }


class SessionManager:
    """In-memory registry of live agent sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}

    def _reap_exited(self) -> None:
        now = time.time()
        stale = [
            sid
            for sid, s in self._sessions.items()
            if s.exited and s.exited_at and (now - s.exited_at) > _EXITED_TTL
        ]
        for sid in stale:
            self._sessions.pop(sid, None)

    async def create(
        self,
        agent: str,
        command: str,
        args: list[str] | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        cols: int = 80,
        rows: int = 24,
    ) -> AgentSession:
        self._reap_exited()
        session = AgentSession(
            id=uuid.uuid4().hex[:12],
            agent=agent,
            command=command,
            cwd=str(cwd) if cwd else "",
            created_at=time.time(),
        )
        session.pty = await PtySession.start(
            command,
            args=args,
            cwd=cwd,
            env=env,
            cols=cols,
            rows=rows,
            on_output=session._on_output,
            on_exit=session._on_exit,
        )
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> AgentSession | None:
        return self._sessions.get(session_id)

    def list(self) -> list[dict]:
        self._reap_exited()
        return [
            s.info()
            for s in sorted(
                self._sessions.values(), key=lambda s: s.created_at, reverse=True
            )
        ]

    async def close(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        if session.pty is not None:
            await session.pty.close()
        for q in list(session.subscribers):
            q.put_nowait(None)
        return True

    async def close_all(self) -> None:
        for sid in list(self._sessions):
            await self.close(sid)


# Module-level singleton (mirrors mesh_state / stream subscribers).
manager = SessionManager()
