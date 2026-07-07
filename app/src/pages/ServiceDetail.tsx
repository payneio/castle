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
import { RelatedDeployments } from "@/components/detail/RelatedDeployments"

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
  const root = (deployment.manifest?.root as string | undefined) ?? undefined
  // The gateway address to launch: a static is always served there (falls back to
  // its id); a systemd service only when it's actually proxied (has a subdomain).
  const launchLabel = deployment.subdomain ?? (isStatic ? deployment.id : undefined)
  const launchUrl = launchLabel ? subdomainUrl(launchLabel) : null

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
        <div className="flex items-center gap-2">
          {!isStatic && health && <HealthBadge status={health.status} latency={health.latency_ms} />}
          {launchUrl && (
            <a
              href={launchUrl}
              target="_blank"
              rel="noopener noreferrer"
              title={`Open ${launchLabel}`}
              aria-label={`Open ${launchLabel} in a new tab`}
              className="p-1.5 rounded-md text-[var(--muted)] hover:text-[var(--primary)] hover:bg-[var(--background)] transition-colors"
            >
              <ExternalLink size={16} />
            </a>
          )}
          {!isStatic && <ServiceControls name={deployment.id} enabled={deployment.enabled} />}
        </div>
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
          {deployment.launcher && (
            <>
              <span className="text-[var(--muted)]">Launch</span>
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

      <RelatedDeployments name={deployment.id} />

      <ConfigPanel
        deployment={deployment}
        configSection={isStatic ? "static" : "services"}
        onRefetch={refetch}
      />

      {deployment.systemd && (
        <SystemdPanel name={deployment.id} systemd={deployment.systemd} />
      )}

      {deployment.managed && (
        <div className="mb-6">
          <h2 className="text-lg font-semibold mb-3">Logs</h2>
          <LogViewer name={deployment.id} />
        </div>
      )}
    </div>
  )
}
