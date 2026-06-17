import { useEffect, useImperativeHandle, useRef, useState, forwardRef } from "react"
import { Maximize2, Minimize2, Pause, Play, Trash2 } from "lucide-react"
import { apiClient } from "@/services/api/client"

interface LogViewerProps {
  name: string
  lines?: number
  follow?: boolean
}

export interface LogViewerHandle {
  clear: () => void
}

export const LogViewer = forwardRef<LogViewerHandle, LogViewerProps>(function LogViewer(
  { name, lines = 50, follow = true },
  ref,
) {
  const [logs, setLogs] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const [maximized, setMaximized] = useState(false)
  // When true, new log lines scroll the view to the bottom. Scrolling up to read
  // pauses it; scrolling back to the bottom (or the play button) resumes.
  const [autoScroll, setAutoScroll] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const preRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (!follow) {
      apiClient
        .get<{ lines: string[] }>(`/logs/${name}?n=${lines}`)
        .then((data) => setLogs(data.lines))
      return
    }

    const url = apiClient.streamUrl(`/logs/${name}?n=${lines}&follow=true`)
    const es = new EventSource(url)
    es.onopen = () => setConnected(true)
    es.onmessage = (e) => {
      setLogs((prev) => {
        const next = [...prev, e.data]
        return next.length > 500 ? next.slice(-500) : next
      })
    }
    es.onerror = () => setConnected(false)
    return () => es.close()
  }, [name, lines, follow])

  const clear = () => setLogs([])
  useImperativeHandle(ref, () => ({ clear }), [])

  // Esc exits fullscreen.
  useEffect(() => {
    if (!maximized) return
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMaximized(false)
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [maximized])

  // Jump to the newest line only while auto-scroll is on. Instant (not smooth) so
  // the scroll-position check below never sees a mid-animation false "scrolled up".
  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView()
  }, [logs, autoScroll])

  // Keep auto-scroll in sync with where the user is: away from the bottom pauses,
  // back at the bottom resumes — so the button and the scroll position never disagree.
  const onScroll = () => {
    const el = preRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setAutoScroll(atBottom)
  }

  const btn =
    "p-1 rounded text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/10 transition-colors"

  return (
    <div
      className={
        maximized
          ? "fixed inset-0 z-50 bg-[var(--background)] flex flex-col"
          : "bg-black/40 border border-[var(--border)] rounded-lg overflow-hidden"
      }
    >
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-[var(--border)] text-xs text-[var(--muted)]">
        <span className="flex items-center gap-2">
          <span>logs: {name}</span>
          {follow && (
            <span className={connected ? "text-green-400" : "text-red-400"}>
              {connected ? "streaming" : "disconnected"}
            </span>
          )}
          {follow && !autoScroll && <span className="text-amber-400">paused</span>}
        </span>
        <span className="flex items-center gap-0.5">
          <button
            onClick={() => setAutoScroll((s) => !s)}
            className={btn}
            title={autoScroll ? "Pause auto-scroll" : "Resume auto-scroll (jump to latest)"}
          >
            {autoScroll ? <Pause size={13} /> : <Play size={13} />}
          </button>
          <button onClick={clear} className={btn} title="Clear">
            <Trash2 size={13} />
          </button>
          <button
            onClick={() => setMaximized((m) => !m)}
            className={btn}
            title={maximized ? "Restore (Esc)" : "Maximize"}
          >
            {maximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        </span>
      </div>
      <pre
        ref={preRef}
        onScroll={onScroll}
        className={`p-3 text-xs font-mono text-gray-300 ${
          maximized ? "flex-1 overflow-auto" : "overflow-x-auto max-h-96 overflow-y-auto"
        }`}
      >
        {logs.length === 0 ? (
          <span className="text-[var(--muted)]">No logs yet</span>
        ) : (
          logs.map((line, i) => (
            <div key={i} className="leading-5 hover:bg-white/5">
              {line}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </pre>
    </div>
  )
})
