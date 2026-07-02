import { useEffect, useRef, useState } from "react"
import { Maximize2, Minimize2 } from "lucide-react"
import { Terminal } from "@xterm/xterm"
import { FitAddon } from "@xterm/addon-fit"
import "@xterm/xterm/css/xterm.css"
import { apiClient } from "@/services/api/client"
import { cn } from "@/lib/utils"

type Status = "connecting" | "connected" | "exited" | "closed" | "error"

interface AgentTerminalProps {
  // Agent name to launch, or "terminal" for the plain login shell.
  agent: string
  // When set, resume this existing live session (replaying its scrollback).
  resumeId?: string
  // Fired once the backend confirms the session id (new or resumed).
  onSession?: (id: string) => void
  // Fill the parent container's height instead of using a fixed height.
  fill?: boolean
  // "continue": launch the agent with its resume_args (reopen its last convo).
  mode?: "continue"
  // Resume one of the agent's OWN past sessions by its id (agent-native).
  resumeSessionId?: string
  // Bump this whenever the terminal's container is resized by an ancestor (e.g.
  // the dock expanding). Triggers a refit that ResizeObserver alone can miss
  // when the size change is driven by a class swap rather than layout reflow.
  fitSignal?: number
  // Strip chrome (header, border, padding) on narrow screens — used when the
  // dock is maximized so the terminal goes edge-to-edge on a phone.
  compact?: boolean
}

export function AgentTerminal({
  agent,
  resumeId,
  onSession,
  fill,
  mode,
  resumeSessionId,
  fitSignal,
  compact,
}: AgentTerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const [status, setStatus] = useState<Status>("connecting")
  const [detail, setDetail] = useState<string>("")
  const [maximized, setMaximized] = useState(false)

  // Fit to the container, then tell the backend pty the new size.
  const refit = () => {
    const term = termRef.current
    const ws = wsRef.current
    if (!term) return
    try {
      fitRef.current?.fit()
    } catch {
      /* container not laid out yet */
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }))
    }
  }

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
    termRef.current = term
    fitRef.current = fit
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
    wsRef.current = ws
    const enc = new TextEncoder()

    ws.onopen = () => {
      setStatus("connected")
      refit()
      // On resume, full-screen TUIs (opencode, claude) don't know a new client
      // attached and won't repaint. A size change forces SIGWINCH → a full
      // redraw of the current frame, so the prior session becomes visible.
      if (resumeId) {
        setTimeout(() => {
          if (ws.readyState !== WebSocket.OPEN) return
          ws.send(
            JSON.stringify({ type: "resize", cols: Math.max(1, term.cols - 1), rows: term.rows }),
          )
          setTimeout(refit, 60)
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

    const ro = new ResizeObserver(() => refit())
    if (containerRef.current) ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      dataDisp.dispose()
      ws.close()
      term.dispose()
      termRef.current = null
      fitRef.current = null
      wsRef.current = null
    }
    // Remounting (new agent / resume target / mode) tears this down and restarts.
  }, [agent, resumeId, mode, resumeSessionId, onSession])

  // An ancestor changed our size (dock expanded/restored/reopened). ResizeObserver
  // usually catches it, but a class-swap + CSS can settle a frame late, so refit
  // across a few frames until the new size stabilizes.
  useEffect(() => {
    let raf = 0
    const start = performance.now()
    const tick = () => {
      refit()
      if (performance.now() - start < 400) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [fitSignal])

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
      className={cn(
        maximized
          ? "fixed inset-0 z-50 bg-[var(--background)] flex flex-col"
          : fill
            ? "h-full flex flex-col bg-black/40 border border-[var(--border)] rounded-lg overflow-hidden"
            : "bg-black/40 border border-[var(--border)] rounded-lg overflow-hidden",
        compact && "max-sm:border-0 max-sm:rounded-none",
      )}
    >
      <div
        className={cn(
          "flex items-center justify-between px-3 py-1.5 border-b border-[var(--border)] text-xs text-[var(--muted)]",
          compact && "max-sm:hidden",
        )}
      >
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
      {/* Sized region + an absolutely-filled xterm mount. The absolute inset-0
          child always has an explicit box equal to its parent, so `fit()` never
          measures a stale/percentage-collapsed height — the terminal tracks the
          panel as it expands. */}
      <div
        className={cn("relative", maximized || fill ? "flex-1 min-h-0" : "h-[560px]")}
      >
        <div
          ref={containerRef}
          className={cn("absolute inset-0 p-2", compact && "max-sm:p-0")}
        />
      </div>
    </div>
  )
}
