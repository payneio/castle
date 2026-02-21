import { useEffect, useRef, useState } from "react"
import { apiClient } from "@/services/api/client"

interface LogViewerProps {
  name: string
  lines?: number
  follow?: boolean
}

export function LogViewer({ name, lines = 50, follow = true }: LogViewerProps) {
  const [logs, setLogs] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!follow) {
      // Static fetch
      apiClient
        .get<{ lines: string[] }>(`/logs/${name}?n=${lines}`)
        .then((data) => setLogs(data.lines))
      return
    }

    // SSE follow
    const url = apiClient.streamUrl(`/logs/${name}?n=${lines}&follow=true`)
    const es = new EventSource(url)

    es.onopen = () => setConnected(true)

    es.onmessage = (e) => {
      setLogs((prev) => {
        const next = [...prev, e.data]
        // Keep last 500 lines in memory
        return next.length > 500 ? next.slice(-500) : next
      })
    }

    es.onerror = () => setConnected(false)

    return () => es.close()
  }, [name, lines, follow])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [logs])

  return (
    <div className="bg-black/40 border border-[var(--border)] rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-[var(--border)] text-xs text-[var(--muted)]">
        <span>logs: {name}</span>
        {follow && (
          <span className={connected ? "text-green-400" : "text-red-400"}>
            {connected ? "streaming" : "disconnected"}
          </span>
        )}
      </div>
      <pre className="p-3 text-xs font-mono text-gray-300 overflow-x-auto max-h-96 overflow-y-auto">
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
}
