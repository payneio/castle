import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { Globe, RefreshCw, FileText, ExternalLink, Cable } from "lucide-react"
import type { GatewayInfo, HealthStatus } from "@/types"
import { useGatewayReload, useCaddyfile } from "@/services/api/hooks"
import { subdomainUrl } from "@/lib/labels"
import { HealthBadge } from "./HealthBadge"
import { GatewaySettings } from "./GatewaySettings"

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

      {/* Routing + public-exposure settings (editable) */}
      <GatewaySettings gateway={gateway} />

      {/* Route table — every gateway route, of every kind */}
      {gateway.routes.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-left">
              <th className="px-4 py-2 font-medium text-[var(--muted)]">Address</th>
              <th className="px-4 py-2 font-medium text-[var(--muted)]">Kind</th>
              <th className="px-4 py-2 font-medium text-[var(--muted)]">Target</th>
              {multiNode && (
                <th className="px-4 py-2 font-medium text-[var(--muted)]">Node</th>
              )}
              <th className="px-4 py-2 font-medium text-[var(--muted)]">Health</th>
            </tr>
          </thead>
          <tbody>
            {gateway.routes.map((route) => {
              // Health applies to proxy/remote targets (a running service);
              // static targets are files on disk.
              const health = route.kind !== "static" && route.name ? statusMap.get(route.name) : undefined
              // The address is a subdomain label — link to its full https URL.
              const url = subdomainUrl(route.address)
              return (
                <tr
                  key={`${route.address}-${route.node}`}
                  className="border-b border-[var(--border)] last:border-b-0 hover:bg-black/20 transition-colors"
                >
                  <td className="px-4 py-2 font-mono text-[var(--primary)]">
                    {(() => {
                      // A public route links to its public URL; otherwise the
                      // internal subdomain URL.
                      const primaryUrl = route.public_url || url
                      const isPublic = !!route.public_url
                      return primaryUrl ? (
                        <a
                          href={primaryUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          title={primaryUrl}
                          className={`inline-flex items-center gap-1 hover:underline ${
                            isPublic ? "text-green-500" : ""
                          }`}
                        >
                          {isPublic && <Cable size={11} className="shrink-0" />}
                          {route.address}
                          <ExternalLink size={11} className="opacity-60 shrink-0" />
                        </a>
                      ) : (
                        route.address
                      )
                    })()}
                  </td>
                  <td className="px-4 py-2">
                    <KindBadge kind={route.kind} />
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-[var(--muted)]">
                    {route.name ? (
                      <Link to={`/deployment/${route.name}`} className="hover:text-[var(--primary)]">
                        {route.kind === "static" ? shortDir(route.target) : route.target}
                      </Link>
                    ) : (
                      route.target
                    )}
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
                    {route.kind === "static" ? (
                      <span className="text-xs text-[var(--muted)]">—</span>
                    ) : (
                      <HealthBadge status={health?.status ?? "unknown"} latency={health?.latency_ms} />
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
          No gateway routes configured.
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

const KIND_STYLE: Record<string, string> = {
  static: "bg-cyan-900/30 text-cyan-300 border-cyan-800",
  proxy: "bg-green-900/30 text-green-300 border-green-800",
  remote: "bg-purple-900/30 text-purple-300 border-purple-800",
}

/** Caddy serves static files; proxy/remote forward to a process. */
function KindBadge({ kind }: { kind: string }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded border ${KIND_STYLE[kind] ?? "text-[var(--muted)]"}`}>
      {kind}
    </span>
  )
}

/** Show the tail of a serve directory (…/app/dist). */
function shortDir(path: string): string {
  const parts = path.split("/").filter(Boolean)
  return parts.length <= 2 ? path : "…/" + parts.slice(-2).join("/")
}
