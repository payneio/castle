import { useParams, Link } from "react-router-dom"
import { Server, ExternalLink, Terminal } from "lucide-react"
import { useService, useStatus, useEventStream, useCaddyfile } from "@/services/api/hooks"
import { runnerLabel } from "@/lib/labels"
import { HealthBadge } from "@/components/HealthBadge"
import { LogViewer } from "@/components/LogViewer"
import { DetailHeader } from "@/components/detail/DetailHeader"
import { ServiceControls } from "@/components/detail/ServiceControls"
import { SystemdPanel } from "@/components/detail/SystemdPanel"
import { ConfigPanel } from "@/components/detail/ConfigPanel"

export function ServiceDetailPage() {
  useEventStream()
  const { name } = useParams<{ name: string }>()
  const { data: deployment, isLoading, error, refetch } = useService(name ?? "")
  const { data: statusResp } = useStatus()
  const health = statusResp?.statuses.find((s) => s.id === name)
  const isGateway = name === "castle-gateway"
  const { data: caddyfile } = useCaddyfile(isGateway)

  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8 text-[var(--muted)]">Loading...</div>
    )
  }

  if (error || !deployment) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8">
        <DetailHeader backTo="/" backLabel="Back" name={name ?? ""} />
        <p className="text-red-400">Service not found</p>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <DetailHeader
        backTo="/"
        backLabel="Back to Services"
        name={deployment.id}
        behavior="daemon"
        stack={deployment.stack}
        source={deployment.source}
      >
        <div className="flex items-center gap-2">
          {health && <HealthBadge status={health.status} latency={health.latency_ms} />}
          <ServiceControls name={deployment.id} health={health} />
        </div>
      </DetailHeader>

      <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
        <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">
          Overview
        </h2>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          {deployment.port && (
            <>
              <span className="text-[var(--muted)]">Port</span>
              <span className="flex items-center gap-1 font-mono">
                <Server size={12} />:{deployment.port}
              </span>
            </>
          )}
          {deployment.health_path && (
            <>
              <span className="text-[var(--muted)]">Health</span>
              <span className="font-mono">{deployment.health_path}</span>
            </>
          )}
          {deployment.proxy_path && (
            <>
              <span className="text-[var(--muted)]">Proxy</span>
              <a
                href={deployment.proxy_path + "/"}
                className="flex items-center gap-1 text-[var(--primary)] hover:underline font-mono"
              >
                <ExternalLink size={12} />{deployment.proxy_path}
              </a>
            </>
          )}
          {deployment.proxy_host && (
            <>
              <span className="text-[var(--muted)]">Host</span>
              <span className="font-mono">{deployment.proxy_host}</span>
            </>
          )}
          {deployment.runner && (
            <>
              <span className="text-[var(--muted)]">Runs</span>
              <span className="flex items-center gap-1">
                <Terminal size={12} />
                {runnerLabel(deployment.runner)}
                {deployment.run_target && <> &middot; <span className="font-mono">{deployment.run_target}</span></>}
              </span>
            </>
          )}
          {deployment.program && (
            <>
              <span className="text-[var(--muted)]">Program</span>
              <Link to={`/programs/${deployment.program}`} className="text-[var(--primary)] hover:underline">
                {deployment.program}
              </Link>
            </>
          )}
          {deployment.port && (
            <>
              <span className="text-[var(--muted)]">Docs</span>
              <a
                href={`http://localhost:${deployment.port}/docs`}
                className="text-[var(--primary)] hover:underline"
              >
                OpenAPI docs
              </a>
            </>
          )}
        </div>
      </div>

      {deployment.systemd && (
        <SystemdPanel name={deployment.id} systemd={deployment.systemd} />
      )}

      {isGateway && caddyfile?.content && (
        <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
          <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider mb-1">
            Caddyfile
          </h2>
          <p className="text-xs text-[var(--muted)] mb-3">
            Generated reverse proxy configuration served by the gateway.
          </p>
          <pre className="text-sm whitespace-pre-wrap bg-[var(--background)] rounded p-3 border border-[var(--border)] font-mono overflow-x-auto">
            {caddyfile.content}
          </pre>
        </div>
      )}

      <ConfigPanel deployment={deployment} configSection="services" onRefetch={refetch} />

      {deployment.managed && (
        <div className="mb-6">
          <h2 className="text-lg font-semibold mb-3">Logs</h2>
          <LogViewer name={deployment.id} />
        </div>
      )}
    </div>
  )
}
