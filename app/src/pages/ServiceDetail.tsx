import { useParams, Link } from "react-router-dom"
import { Server, ExternalLink, Terminal } from "lucide-react"
import { useService, useStatus, useCaddyfile } from "@/services/api/hooks"
import { launcherLabel, subdomainUrl } from "@/lib/labels"
import { HealthBadge } from "@/components/HealthBadge"
import { LogViewer } from "@/components/LogViewer"
import { DetailHeader } from "@/components/detail/DetailHeader"
import { ServiceControls } from "@/components/detail/ServiceControls"
import { SystemdPanel } from "@/components/detail/SystemdPanel"
import { ConfigPanel } from "@/components/detail/ConfigPanel"

export function ServiceDetailPage() {
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

  // A static is a caddy-served site, not a systemd unit — no start/stop, no logs;
  // it shows its served URL and the dir it serves instead of a port/launcher.
  const isStatic = deployment.kind === "static" || deployment.manager === "caddy"
  const servedUrl = subdomainUrl(deployment.subdomain ?? deployment.id)
  const root = (deployment.manifest?.root as string | undefined) ?? undefined

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <DetailHeader
        backTo="/services"
        backLabel="Back to Services"
        name={deployment.id}
        kind={isStatic ? "static" : "service"}
        stack={deployment.stack}
        source={deployment.source}
      >
        {!isStatic && (
          <div className="flex items-center gap-2">
            {health && <HealthBadge status={health.status} latency={health.latency_ms} />}
            <ServiceControls name={deployment.id} health={health} />
          </div>
        )}
      </DetailHeader>

      <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
        <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">
          Overview
        </h2>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          {isStatic && (
            <>
              <span className="text-[var(--muted)]">Status</span>
              <span className="text-green-400">
                ● served by the gateway
                <span className="text-xs text-[var(--muted)]"> · manager: caddy</span>
              </span>
              {servedUrl && (
                <>
                  <span className="text-[var(--muted)]">Served at</span>
                  <a
                    href={servedUrl}
                    className="flex items-center gap-1 min-w-0 break-all text-[var(--primary)] hover:underline font-mono"
                  >
                    <ExternalLink size={12} className="shrink-0" />{deployment.subdomain ?? deployment.id}
                  </a>
                </>
              )}
              {root && (
                <>
                  <span className="text-[var(--muted)]">Root</span>
                  <span className="font-mono break-all">{root}</span>
                </>
              )}
            </>
          )}
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
              <span className="font-mono break-all">{deployment.health_path}</span>
            </>
          )}
          {deployment.subdomain && (
            <>
              <span className="text-[var(--muted)]">Subdomain</span>
              <a
                href={subdomainUrl(deployment.subdomain) ?? undefined}
                className="flex items-center gap-1 min-w-0 break-all text-[var(--primary)] hover:underline font-mono"
              >
                <ExternalLink size={12} className="shrink-0" />{deployment.subdomain}
              </a>
            </>
          )}
          {deployment.launcher && (
            <>
              <span className="text-[var(--muted)]">Runs</span>
              <span className="flex items-center gap-1 min-w-0">
                <Terminal size={12} className="shrink-0" />
                {launcherLabel(deployment.launcher)}
                {deployment.run_target && <> &middot; <span className="font-mono break-all">{deployment.run_target}</span></>}
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

      <ConfigPanel
        deployment={deployment}
        configSection={isStatic ? "static" : "services"}
        onRefetch={refetch}
      />

      {deployment.managed && (
        <div className="mb-6">
          <h2 className="text-lg font-semibold mb-3">Logs</h2>
          <LogViewer name={deployment.id} />
        </div>
      )}
    </div>
  )
}
