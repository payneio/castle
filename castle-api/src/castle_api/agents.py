"""Agent terminal UX — list agents, run/resume them in a terminal over WebSocket.

Castle is assistant-agnostic: it launches a configured command (or a shell) in a
real tty and streams raw bytes to an xterm.js terminal in the browser. Sessions
outlive their WebSocket connection (and, with the tmux backend, a castle-api
restart), so they can be listed, resumed, and killed. The session backend lives
in `agent_sessions.py`; this module is the HTTP/WebSocket surface.
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
from castle_api.agent_sessions import manager
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
async def get_sessions() -> list[dict]:
    """List live terminal sessions (running, backend-managed)."""
    return await manager.list()


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
    """Kill a session and drop it from the backend."""
    ok = await manager.close(session_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="session not found"
        )
    return {"status": "closed", "id": session_id}


# --- WebSocket: interactive session ----------------------------------------


def _login_shell() -> str:
    return os.environ.get("SHELL") or "/bin/bash"


async def _build_launch(
    name: str, cont: bool = False, resume_session: str | None = None
) -> tuple[str, list[str], str, dict[str, str]]:
    """Return (agent_label, argv, cwd, env) for a new session.

    Everything runs under the user's *interactive login* shell (`-lic`) so it
    inherits exactly the environment a real terminal would — the systemd service
    env is stripped down and would otherwise miss vars from shell rc files (API
    keys, etc.). Agents are `exec`'d so the terminal's foreground process is the
    agent itself. `cont` appends the agent's `resume_args`; `resume_session`
    builds its resume-by-id argv — castle only passes declared flags through.
    """
    shell = _login_shell()
    if name == TERMINAL_AGENT:
        return TERMINAL_AGENT, [shell, "-l"], default_cwd(), {}
    agent = resolve_agent(name)
    if agent is None:
        raise LookupError(f"unknown agent: {name}")
    if not agent.available:
        raise LookupError(f"agent not installed: {name}")
    if resume_session:
        inner = resume_argv(agent, resume_session)
        if inner is None:
            raise LookupError(f"agent cannot resume by id: {name}")
    else:
        inner = [agent.resolved_command or agent.command, *agent.args]
        if cont and agent.resume_args:
            inner += agent.resume_args
    argv = [shell, "-lic", f"exec {shlex.join(inner)}"]
    return name, argv, agent.cwd, agent.env


@router.websocket("/{name}/session")
async def agent_session(ws: WebSocket, name: str) -> None:
    """Run (or resume) an agent in a terminal; stream it to the browser.

    Query params (mutually exclusive, all optional):
    - `session=<id>`         resume an existing live session.
    - `resume_session=<id>`  start the agent resumed to one of *its own* past
                             sessions (agent-native, by id).
    - `mode=continue`        start the agent with its `resume_args`.
    Disconnecting detaches — it does NOT kill the session.
    """
    if not _origin_allowed(ws.headers.get("origin")):
        await ws.close(code=1008)  # policy violation
        return

    resume_id = ws.query_params.get("session")
    session_id: str
    is_resume = False
    agent_label = name

    try:
        if resume_id:
            info = await manager.get_info(resume_id)
            if not info or not info.get("running"):
                await ws.accept()
                await ws.send_json({"type": "error", "error": "session not resumable"})
                await ws.close()
                return
            session_id = resume_id
            is_resume = True
            agent_label = info.get("agent") or name
        else:
            cont = ws.query_params.get("mode") == "continue"
            resume_session = ws.query_params.get("resume_session")
            agent_label, argv, cwd, env = await _build_launch(
                name, cont, resume_session
            )
            session_id = await manager.create(
                agent_label, argv, cwd, env, cols=80, rows=24
            )
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

    await ws.accept()
    att = await manager.attach(session_id, cols=80, rows=24)
    if att is None:
        await ws.send_json({"type": "error", "error": "session not attachable"})
        await ws.close()
        return

    await ws.send_json(
        {
            "type": "session",
            "id": session_id,
            "agent": agent_label,
            "resumed": is_resume,
        }
    )

    async def pump() -> None:
        try:
            async for chunk in att.reader():
                if ws.application_state != WebSocketState.CONNECTED:
                    break
                await ws.send_bytes(chunk)
            # reader ended without cancellation → the session ended
            if ws.application_state == WebSocketState.CONNECTED:
                info = await manager.get_info(session_id)
                code = info.get("exit_code") if info else None
                await ws.send_json({"type": "exit", "code": code})
                await ws.close()
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
            if data is not None:
                att.write(data)
            elif text is not None:
                try:
                    ctrl = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if ctrl.get("type") == "resize":
                    att.resize(int(ctrl["cols"]), int(ctrl["rows"]))
                elif ctrl.get("type") == "input":
                    att.write(str(ctrl.get("data", "")).encode())
    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()
        await att.aclose()
        # Intentionally do NOT close the session — it lives on for resume.
