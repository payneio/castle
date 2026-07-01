"""Agent terminal UX — list agents, run/resume them in a pty over WebSocket.

Castle is assistant-agnostic: it launches a configured command (or a shell) in a
real tty and streams raw bytes to an xterm.js terminal in the browser. Sessions
outlive their WebSocket connection, so they can be listed, resumed, and killed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from starlette.websockets import WebSocketState

from castle_api.agent_registry import (
    default_cwd,
    list_agent_history,
    list_agents,
    resolve_agent,
    resume_argv,
)
from castle_api.agent_sessions import AgentSession, manager
from castle_api.config import get_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])

# The reserved agent name that launches the user's login shell (Option A: plain
# terminal). Not a configured agent — Castle knows nothing about what you run in it.
TERMINAL_AGENT = "terminal"


# --- Origin allowlist (this endpoint is an interactive shell) ---------------


def _origin_allowed(origin: str | None) -> bool:
    """Allow same-node/local and configured-domain origins for the WS handshake.

    CORS (`*`) governs XHR, not WebSocket upgrades, so we gate the handshake
    here. Non-browser clients (no Origin) and localhost are allowed; browser
    origins must match the gateway domain (or `CASTLE_API_TERMINAL_ORIGINS`).
    Set `CASTLE_API_ALLOW_ALL_ORIGINS=1` to disable the check entirely.
    """
    if os.environ.get("CASTLE_API_ALLOW_ALL_ORIGINS"):
        return True
    if not origin:
        return True  # curl/websocat and other non-browser clients
    host = (urlparse(origin).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        domain = get_config().gateway.domain
    except Exception:
        domain = None
    if domain and (host == domain or host.endswith("." + domain)):
        return True
    extra = os.environ.get("CASTLE_API_TERMINAL_ORIGINS", "")
    allowed = {h.strip().lower() for h in extra.split(",") if h.strip()}
    return host in allowed


# --- HTTP: agents + sessions ------------------------------------------------


@router.get("")
def get_agents() -> list[dict]:
    """List launchable agents with availability (binary present) + default cwd."""
    return [a.info() for a in list_agents()]


@router.get("/sessions")
def get_sessions() -> list[dict]:
    """List live terminal sessions (running or recently exited)."""
    return manager.list()


@router.get("/history")
async def get_history() -> list[dict]:
    """Unified list of agents' own past sessions (from each agent's declared
    `sessions.list_command`), newest first. Agents without the capability
    (or with none stored) simply contribute nothing."""
    agents = [a for a in list_agents() if a.available and a.can_list_sessions]
    results = await asyncio.gather(*(list_agent_history(a) for a in agents))
    rows = [row for agent_rows in results for row in agent_rows]
    try:
        rows.sort(key=lambda r: r["time"] or 0, reverse=True)
    except TypeError:
        pass
    return rows


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict:
    """Kill a session's process group and drop it from the registry."""
    ok = await manager.close(session_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="session not found"
        )
    return {"status": "closed", "id": session_id}


# --- WebSocket: interactive session ----------------------------------------


def _login_shell() -> str:
    return os.environ.get("SHELL") or "/bin/bash"


async def _new_session(
    name: str, cont: bool = False, resume_session: str | None = None
) -> AgentSession:
    """Create a session for a named agent, or the reserved login shell.

    Everything runs under the user's *interactive login* shell (`-lic`) so it
    inherits exactly the environment a real terminal would — the systemd service
    env is stripped down and would otherwise miss vars set in shell rc files
    (API keys, etc.). Agents are `exec`'d so the pty's foreground process is the
    agent itself (clean signals + exit).

    ``cont`` appends the agent's ``resume_args`` (open its own picker / continue).
    ``resume_session`` builds the agent's resume-by-id argv for a specific past
    session. Either way castle only passes declared flags through — it never
    reads the agent's session storage.
    """
    shell = _login_shell()
    if name == TERMINAL_AGENT:
        return await manager.create(
            TERMINAL_AGENT, shell, args=["-l"], cwd=default_cwd()
        )
    agent = resolve_agent(name)
    if agent is None:
        raise LookupError(f"unknown agent: {name}")
    if not agent.available:
        raise LookupError(f"agent not installed: {name}")
    if resume_session:
        argv = resume_argv(agent, resume_session)
        if argv is None:
            raise LookupError(f"agent cannot resume by id: {name}")
    else:
        argv = [agent.resolved_command or agent.command, *agent.args]
        if cont and agent.resume_args:
            argv += agent.resume_args
    launch = shlex.join(argv)
    return await manager.create(
        name,
        shell,
        args=["-lic", f"exec {launch}"],
        cwd=agent.cwd,
        env=agent.env,  # explicit per-agent overrides; the login shell sets PATH
    )


@router.websocket("/{name}/session")
async def agent_session(ws: WebSocket, name: str) -> None:
    """Run (or resume) an agent in a pty; stream it to the browser terminal.

    Query param `session=<id>` resumes an existing live session (replaying its
    scrollback); otherwise a new session is created for `name` (or the reserved
    `terminal` shell). Disconnecting detaches — it does NOT kill the session.
    """
    if not _origin_allowed(ws.headers.get("origin")):
        await ws.close(code=1008)  # policy violation
        return

    resume_id = ws.query_params.get("session")

    # Resolve the target session (before accept only for hard rejects).
    session: AgentSession | None = None
    if resume_id:
        session = manager.get(resume_id)
        if session is None or not session.running:
            await ws.accept()
            await ws.send_json({"type": "error", "error": "session not resumable"})
            await ws.close()
            return
    else:
        cont = ws.query_params.get("mode") == "continue"
        resume_session = ws.query_params.get("resume_session")
        try:
            session = await _new_session(name, cont=cont, resume_session=resume_session)
        except LookupError as e:
            await ws.accept()
            await ws.send_json({"type": "error", "error": str(e)})
            await ws.close()
            return
        except Exception:
            logger.exception("failed to launch agent %s", name)
            await ws.accept()
            await ws.send_json({"type": "error", "error": "failed to launch"})
            await ws.close()
            return

    assert session is not None  # narrowed by the branches above
    await ws.accept()

    # Subscribe + snapshot scrollback atomically (no await between → the output
    # callback, which runs in this same event loop, cannot interleave), so a
    # resumed client gets the buffer once with no duplication or gap.
    q = session.subscribe()
    snapshot = bytes(session.scrollback)

    await ws.send_json(
        {
            "type": "session",
            "id": session.id,
            "agent": session.agent,
            "resumed": bool(resume_id),
        }
    )
    if snapshot:
        await ws.send_bytes(snapshot)

    async def pump() -> None:
        try:
            while True:
                chunk = await q.get()
                if chunk is None:  # child exited
                    if ws.application_state == WebSocketState.CONNECTED:
                        await ws.send_json({"type": "exit", "code": session.exit_code})
                    break
                if ws.application_state != WebSocketState.CONNECTED:
                    break
                await ws.send_bytes(chunk)
        except Exception:
            pass

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes")
            text = msg.get("text")
            if data is not None and session.pty is not None:
                session.pty.write(data)
            elif text is not None and session.pty is not None:
                try:
                    ctrl = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if ctrl.get("type") == "resize":
                    session.pty.resize(int(ctrl["cols"]), int(ctrl["rows"]))
                elif ctrl.get("type") == "input":
                    session.pty.write(str(ctrl.get("data", "")).encode())
    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()
        session.unsubscribe(q)
        # Intentionally do NOT close the session here — it lives on for resume.
        # Sessions are ended via DELETE /agents/sessions/{id}, when the child
        # exits, or by idle reaping.
