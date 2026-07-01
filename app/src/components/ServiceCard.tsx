import { ExternalLink, Play, RefreshCw, Server, Square, Terminal } from "lucide-react"
import { Link } from "react-router-dom"
import type { ServiceSummary, HealthStatus } from "@/types"
import { useServiceAction } from "@/services/api/hooks"
import { launcherLabel, subdomainUrl } from "@/lib/labels"
import { HealthBadge } from "./HealthBadge"
import { StackBadge } from "./StackBadge"

interface ServiceCardProps {
  service: ServiceSummary
  health?: HealthStatus
}

export function ServiceCard({ service, health }: ServiceCardProps) {
  const hasHttp = service.port != null
  const { mutate, isPending } = useServiceAction()

  const doAction = (action: string) => {
    mutate({ name: service.id, action })
  }

  const isDown = health?.status === "down"

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

      <div className="flex gap-1.5 mb-2">
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
            {isDown && (
              <button
                onClick={() => doAction("start")}
                disabled={isPending}
                className="p-1 rounded hover:bg-green-800/30 text-green-400 transition-colors disabled:opacity-40"
                title="Start"
              >
                <Play size={14} />
              </button>
            )}
            <button
              onClick={() => doAction("restart")}
              disabled={isPending}
              className="p-1 rounded hover:bg-blue-800/30 text-blue-400 transition-colors disabled:opacity-40"
              title="Restart"
            >
              <RefreshCw size={14} />
            </button>
            {!isDown && (
              <button
                onClick={() => doAction("stop")}
                disabled={isPending}
                className="p-1 rounded hover:bg-red-800/30 text-red-400 transition-colors disabled:opacity-40"
                title="Stop"
              >
                <Square size={14} />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
