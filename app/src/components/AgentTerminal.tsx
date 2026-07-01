import { useEffect, useRef, useState } from "react"
import { Maximize2, Minimize2 } from "lucide-react"
import { Terminal } from "@xterm/xterm"
import { FitAddon } from "@xterm/addon-fit"
import "@xterm/xterm/css/xterm.css"
import { apiClient } from "@/services/api/client"

type Status = "connecting" | "connected" | "exited" | "closed" | "error"

interface AgentTerminalProps {
  // Agent name to launch, or "terminal" for the plain login shell.
  agent: string
  // When set, resume this existing session instead of creating a new one.
  resumeId?: string
  // Fired once the backend confirms the session id (new or resumed).
  onSession?: (id: string) => void
  // Fill the parent container's height instead of using a fixed height.
  fill?: boolean
  // "continue": launch the agent with its resume_args (reopen its last convo).
  mode?: "continue"
  // Resume one of the agent's OWN past sessions by its id (agent-native).
  resumeSessionId?: string
}

export function AgentTerminal({
  agent,
  resumeId,
  onSession,
  fill,
  mode,
  resumeSessionId,
}: AgentTerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<Status>("connecting")
  const [detail, setDetail] = useState<string>("")
  const [maximized, setMaximized] = useState(false)

  useEffect(() => {
    const term = new Terminal({
      convertEol: false,
      cursorBlink: true,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
      fontSize: 13,
      theme: { background: "#0a0a0a", foreground: "#d1d5db" },
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(containerRef.current!)
    try {
      fit.fit()
    } catch {
      /* container not laid out yet */
    }

    const path = resumeId
      ? `/agents/${agent}/session?session=${encodeURIComponent(resumeId)}`
      : resumeSessionId
        ? `/agents/${agent}/session?resume_session=${encodeURIComponent(resumeSessionId)}`
        : mode === "continue"
          ? `/agents/${agent}/session?mode=continue`
          : `/agents/${agent}/session`
    const ws = new WebSocket(apiClient.wsUrl(path))
    ws.binaryType = "arraybuffer"
    const enc = new TextEncoder()

    const sendResize = () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }))
      }
    }

    ws.onopen = () => {
      setStatus("connected")
      sendResize()
      // On resume, full-screen TUIs (opencode, claude) don't know a new client
      // attached and won't repaint. A size change forces SIGWINCH → a full
      // redraw of the current frame, so the prior session becomes visible.
      if (resumeId) {
        setTimeout(() => {
          if (ws.readyState !== WebSocket.OPEN) return
          ws.send(
            JSON.stringify({ type: "resize", cols: Math.max(1, term.cols - 1), rows: term.rows }),
          )
          setTimeout(sendResize, 60)
        }, 80)
      }
      term.focus()
    }
    ws.onmessage = (e) => {
      if (typeof e.data === "string") {
        let msg: { type?: string; id?: string; code?: number; error?: string }
        try {
          msg = JSON.parse(e.data)
        } catch {
          return
        }
        if (msg.type === "session" && msg.id) {
          onSession?.(msg.id)
        } else if (msg.type === "exit") {
          setStatus("exited")
          setDetail(`exit ${msg.code ?? "?"}`)
          term.write(`\r\n\x1b[90m[process exited: ${msg.code ?? "?"}]\x1b[0m\r\n`)
        } else if (msg.type === "error") {
          setStatus("error")
          setDetail(msg.error ?? "error")
          term.write(`\r\n\x1b[31m[error: ${msg.error ?? "unknown"}]\x1b[0m\r\n`)
        }
      } else {
        term.write(new Uint8Array(e.data as ArrayBuffer))
      }
    }
    ws.onclose = () => setStatus((s) => (s === "exited" || s === "error" ? s : "closed"))
    ws.onerror = () => setStatus((s) => (s === "connecting" ? "error" : s))

    const dataDisp = term.onData((d) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(enc.encode(d))
    })

    const ro = new ResizeObserver(() => {
      try {
        fit.fit()
      } catch {
        /* ignore */
      }
      sendResize()
    })
    if (containerRef.current) ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      dataDisp.dispose()
      ws.close()
      term.dispose()
    }
    // Remounting (new agent / resume target / mode) tears this down and restarts.
  }, [agent, resumeId, mode, resumeSessionId, onSession])

  const statusColor =
    status === "connected"
      ? "text-green-400"
      : status === "connecting"
        ? "text-amber-400"
        : status === "error"
          ? "text-red-400"
          : "text-[var(--muted)]"

  const btn =
    "p-1 rounded text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/10 transition-colors"

  return (
    <div
      className={
        maximized
          ? "fixed inset-0 z-50 bg-[var(--background)] flex flex-col"
          : fill
            ? "h-full flex flex-col bg-black/40 border border-[var(--border)] rounded-lg overflow-hidden"
            : "bg-black/40 border border-[var(--border)] rounded-lg overflow-hidden"
      }
    >
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-[var(--border)] text-xs text-[var(--muted)]">
        <span className="flex items-center gap-2">
          <span>terminal: {agent}</span>
          <span className={statusColor}>
            {status}
            {detail ? ` · ${detail}` : ""}
          </span>
        </span>
        {/* In dock (fill) mode the surrounding panel owns sizing/expansion, so
            the inner maximize is hidden (a fixed-inset child can't escape the
            panel's transformed containing block anyway). */}
        {!fill && (
          <button
            onClick={() => setMaximized((m) => !m)}
            className={btn}
            title={maximized ? "Restore" : "Maximize"}
          >
            {maximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        )}
      </div>
      <div
        ref={containerRef}
        className={maximized || fill ? "flex-1 min-h-0 p-2" : "h-[560px] p-2"}
      />
    </div>
  )
}
