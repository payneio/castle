import { useParams } from "react-router-dom"
import { Clock } from "lucide-react"
import { useComponent, useStatus, useEventStream } from "@/services/api/hooks"
import { LogViewer } from "@/components/LogViewer"
import { DetailHeader } from "@/components/detail/DetailHeader"
import { ServiceControls } from "@/components/detail/ServiceControls"
import { SystemdPanel } from "@/components/detail/SystemdPanel"
import { ConfigPanel } from "@/components/detail/ConfigPanel"

export function ScheduledDetailPage() {
  useEventStream()
  const { name } = useParams<{ name: string }>()
  const { data: component, isLoading, error, refetch } = useComponent(name ?? "")
  const { data: statusResp } = useStatus()
  const health = statusResp?.statuses.find((s) => s.id === name)

  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8 text-[var(--muted)]">Loading...</div>
    )
  }

  if (error || !component) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8">
        <DetailHeader backTo="/" backLabel="Back" name={name ?? ""} />
        <p className="text-red-400">Scheduled job not found</p>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <DetailHeader
        backTo="/"
        backLabel="Back to Jobs"
        name={component.id}
        behavior={component.behavior}
        stack={component.stack}
        source={component.source}
      >
        <ServiceControls name={component.id} health={health} />
      </DetailHeader>

      {component.schedule && (
        <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
          <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">
            Schedule
          </h2>
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <span className="text-[var(--muted)]">Cron</span>
            <span className="flex items-center gap-2 font-mono">
              <Clock size={14} className="text-[var(--muted)]" />
              {component.schedule}
            </span>
            {component.systemd && (
              <>
                <span className="text-[var(--muted)]">Timer unit</span>
                <span className="font-mono">
                  {component.systemd.unit_name.replace(".service", ".timer")}
                </span>
              </>
            )}
          </div>
        </div>
      )}

      {component.systemd && (
        <SystemdPanel name={component.id} systemd={component.systemd} />
      )}

      <ConfigPanel component={component} configSection="jobs" onRefetch={refetch} />

      {component.managed && (
        <div className="mb-6">
          <h2 className="text-lg font-semibold mb-3">Logs</h2>
          <LogViewer name={component.id} />
        </div>
      )}
    </div>
  )
}
