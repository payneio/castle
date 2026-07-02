import { ExternalLink, Power, RefreshCw, Server, Terminal } from "lucide-react"
import { Link } from "react-router-dom"
import type { ServiceSummary, HealthStatus } from "@/types"
import { useServiceAction, useSetEnabled } from "@/services/api/hooks"
import { launcherLabel, subdomainUrl } from "@/lib/labels"
import { HealthBadge } from "./HealthBadge"
import { StackBadge } from "./StackBadge"
import { KindBadge } from "./KindBadge"

interface ServiceCardProps {
  service: ServiceSummary
  health?: HealthStatus
}

export function ServiceCard({ service, health }: ServiceCardProps) {
  const hasHttp = service.port != null
  const restart = useServiceAction()
  const setEnabled = useSetEnabled()
  const busy = restart.isPending || setEnabled.isPending

  return (
    <div className="relative bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 hover:border-[var(--primary)] transition-colors">
      <div className="flex items-start justify-between mb-2">
        <Link
          to={`/services/${service.id}`}
          className="text-base font-semibold hover:text-[var(--primary)] transition-colors after:absolute after:inset-0"
        >
          {service.id}
        </Link>
        {health ? (
          <HealthBadge status={health.status} latency={health.latency_ms} />
        ) : hasHttp ? (
          <HealthBadge status="unknown" />
        ) : null}
      </div>

      <div className="flex items-center gap-1.5 mb-2">
        {/* A static (caddy-served) "service" is distinguished from a systemd one. */}
        {service.kind === "static" && <KindBadge kind="static" />}
        <StackBadge stack={service.stack} />
      </div>

      {service.description && (
        <p className="text-sm text-[var(--muted)] mb-3">{service.description}</p>
      )}

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 text-xs text-[var(--muted)]">
          {service.port && (
            <span className="flex items-center gap-1 font-mono">
              <Server size={12} />:{service.port}
            </span>
          )}
          {service.launcher && (
            <span className="flex items-center gap-1">
              <Terminal size={12} />
              {launcherLabel(service.launcher)}
            </span>
          )}
          {service.subdomain && (
            <a
              href={subdomainUrl(service.subdomain) ?? undefined}
              className="relative z-10 flex items-center gap-1 text-[var(--primary)] hover:underline"
            >
              <ExternalLink size={12} />
              {service.subdomain}
            </a>
          )}
          {service.port && (
            <a
              href={`http://localhost:${service.port}/docs`}
              className="relative z-10 text-[var(--primary)] hover:underline"
            >
              Docs
            </a>
          )}
        </div>

        {service.managed && (
          <div className="relative z-10 flex items-center gap-1">
            <button
              onClick={() => setEnabled.mutate({ name: service.id, enabled: !service.enabled })}
              disabled={busy}
              className={`p-1 rounded transition-colors disabled:opacity-40 ${
                service.enabled
                  ? "hover:bg-red-800/30 text-red-400"
                  : "hover:bg-green-800/30 text-green-400"
              }`}
              title={service.enabled ? "Disable" : "Enable"}
            >
              <Power size={14} />
            </button>
            {service.enabled && (
              <button
                onClick={() => restart.mutate({ name: service.id, action: "restart" })}
                disabled={busy}
                className="p-1 rounded hover:bg-blue-800/30 text-blue-400 transition-colors disabled:opacity-40"
                title="Restart"
              >
                <RefreshCw size={14} className={restart.isPending ? "animate-spin" : ""} />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
