import { useRef } from "react"
import { useParams } from "react-router-dom"
import { Server, ExternalLink, Terminal, Trash2 } from "lucide-react"
import { useService, useStatus, useEventStream, useCaddyfile } from "@/services/api/hooks"
import { runnerLabel } from "@/lib/labels"
import { HealthBadge } from "@/components/HealthBadge"
import { LogViewer, type LogViewerHandle } from "@/components/LogViewer"
import { DetailHeader } from "@/components/detail/DetailHeader"
import { ServiceControls } from "@/components/detail/ServiceControls"
import { SystemdPanel } from "@/components/detail/SystemdPanel"
import { ConfigPanel } from "@/components/detail/ConfigPanel"

export function ServiceDetailPage() {
  useEventStream()
  const logRef = useRef<LogViewerHandle>(null)
  const { name } = useParams<{ name: string }>()
  const { data: component, isLoading, error, refetch } = useService(name ?? "")
  const { data: statusResp } = useStatus()
  const health = statusResp?.statuses.find((s) => s.id === name)
  const isGateway = name === "castle-gateway"
  const { data: caddyfile } = useCaddyfile(isGateway)

  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8 text-[var(--muted)]">Loading...</div>
    )
  }

  if (error || !component) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8">
        <DetailHeader backTo="/" backLabel="Back" name={name ?? ""} />
        <p className="text-red-400">Service not found</p>
      </div>
    )
  }

  const runner = (component.manifest.run as Record<string, unknown>)?.runner as string | undefined

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <DetailHeader
        backTo="/"
        backLabel="Back to Services"
        name={component.id}
        behavior="daemon"
        stack={component.stack}
        source={component.source}
      >
        <div className="flex items-center gap-2">
          {health && <HealthBadge status={health.status} latency={health.latency_ms} />}
          <ServiceControls name={component.id} health={health} />
        </div>
      </DetailHeader>

      <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
        <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">
          Overview
        </h2>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          {component.port && (
            <>
              <span className="text-[var(--muted)]">Port</span>
              <span className="flex items-center gap-1 font-mono">
                <Server size={12} />:{component.port}
              </span>
            </>
          )}
          {component.health_path && (
            <>
              <span className="text-[var(--muted)]">Health</span>
              <span className="font-mono">{component.health_path}</span>
            </>
          )}
          {component.proxy_path && (
            <>
              <span className="text-[var(--muted)]">Proxy</span>
              <a
                href={component.proxy_path + "/"}
                className="flex items-center gap-1 text-[var(--primary)] hover:underline font-mono"
              >
                <ExternalLink size={12} />{component.proxy_path}
              </a>
            </>
          )}
          {runner && (
            <>
              <span className="text-[var(--muted)]">Runner</span>
              <span className="flex items-center gap-1">
                <Terminal size={12} />
                {runnerLabel(runner)}
                {(component.manifest.run as Record<string, string>)?.program && (
                  <> &middot; {(component.manifest.run as Record<string, string>).program}</>
                )}
              </span>
            </>
          )}
          {component.port && (
            <>
              <span className="text-[var(--muted)]">Docs</span>
              <a
                href={`http://localhost:${component.port}/docs`}
                className="text-[var(--primary)] hover:underline"
              >
                OpenAPI docs
              </a>
            </>
          )}
        </div>
      </div>

      {component.systemd && (
        <SystemdPanel name={component.id} systemd={component.systemd} />
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

      <ConfigPanel component={component} configSection="services" onRefetch={refetch} />

      {component.managed && (
        <div className="mb-6">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold">Logs</h2>
            <button
              onClick={() => logRef.current?.clear()}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded border border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--foreground)] transition-colors"
            >
              <Trash2 size={14} /> Clear
            </button>
          </div>
          <LogViewer ref={logRef} name={component.id} />
        </div>
      )}
    </div>
  )
}
