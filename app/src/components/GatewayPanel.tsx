import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { Globe, RefreshCw, FileText } from "lucide-react"
import type { GatewayInfo, HealthStatus } from "@/types"
import { useGatewayReload, useCaddyfile } from "@/services/api/hooks"
import { HealthBadge } from "./HealthBadge"

interface GatewayPanelProps {
  gateway: GatewayInfo
  statuses: HealthStatus[]
}

export function GatewayPanel({ gateway, statuses }: GatewayPanelProps) {
  const statusMap = new Map(statuses.map((s) => [s.id, s]))
  const { mutate: reload, isPending: reloading } = useGatewayReload()
  const [showCaddyfile, setShowCaddyfile] = useState(false)
  const { data: caddyfileData } = useCaddyfile(showCaddyfile)

  const multiNode = useMemo(() => {
    const nodes = new Set(gateway.routes.map((r) => r.node))
    return nodes.size > 1
  }, [gateway.routes])

  return (
    <section className="border border-[var(--border)] rounded-lg overflow-hidden bg-[var(--card)]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <Globe size={16} className="text-[var(--primary)]" />
          <h2 className="font-semibold">Gateway</h2>
          <span className="text-sm text-[var(--muted)]">
            {gateway.hostname} &middot; port {gateway.port} &middot; {gateway.routes.length} route{gateway.routes.length !== 1 ? "s" : ""}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => reload()}
            disabled={reloading}
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded bg-[var(--border)] hover:bg-[var(--border)]/80 text-[var(--muted)] hover:text-[var(--foreground)] transition-colors disabled:opacity-40"
            title="Regenerate Caddyfile and reload Caddy"
          >
            <RefreshCw size={12} className={reloading ? "animate-spin" : ""} />
            Reload
          </button>
          <button
            onClick={() => setShowCaddyfile((v) => !v)}
            className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded transition-colors ${
              showCaddyfile
                ? "bg-[var(--primary)] text-white"
                : "bg-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
            title="View generated Caddyfile"
          >
            <FileText size={12} />
            Caddyfile
          </button>
        </div>
      </div>

      {/* Route table */}
      {gateway.routes.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-left">
              <th className="px-4 py-2 font-medium text-[var(--muted)]">Path</th>
              <th className="px-4 py-2 font-medium text-[var(--muted)]">Component</th>
              <th className="px-4 py-2 font-medium text-[var(--muted)]">Port</th>
              {multiNode && (
                <th className="px-4 py-2 font-medium text-[var(--muted)]">Node</th>
              )}
              <th className="px-4 py-2 font-medium text-[var(--muted)]">Health</th>
            </tr>
          </thead>
          <tbody>
            {gateway.routes.map((route) => {
              const health = statusMap.get(route.component)
              return (
                <tr
                  key={route.path}
                  className="border-b border-[var(--border)] last:border-b-0 hover:bg-black/20 transition-colors"
                >
                  <td className="px-4 py-2 font-mono text-[var(--primary)]">
                    {route.path}
                  </td>
                  <td className="px-4 py-2">
                    <Link
                      to={`/component/${route.component}`}
                      className="hover:text-[var(--primary)] transition-colors"
                    >
                      {route.component}
                    </Link>
                  </td>
                  <td className="px-4 py-2 font-mono text-[var(--muted)]">
                    {route.target_port}
                  </td>
                  {multiNode && (
                    <td className="px-4 py-2">
                      <Link
                        to={`/node/${route.node}`}
                        className="text-[var(--muted)] hover:text-[var(--foreground)] transition-colors"
                      >
                        {route.node}
                      </Link>
                    </td>
                  )}
                  <td className="px-4 py-2">
                    {health ? (
                      <HealthBadge status={health.status} latency={health.latency_ms} />
                    ) : (
                      <HealthBadge status="unknown" />
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      {gateway.routes.length === 0 && (
        <p className="px-4 py-6 text-center text-[var(--muted)] text-sm">
          No proxy routes configured.
        </p>
      )}

      {/* Caddyfile viewer */}
      {showCaddyfile && caddyfileData && (
        <div className="border-t border-[var(--border)]">
          <pre className="px-4 py-3 text-xs font-mono text-[var(--muted)] overflow-x-auto max-h-64 overflow-y-auto">
            {caddyfileData.content}
          </pre>
        </div>
      )}
    </section>
  )
}
