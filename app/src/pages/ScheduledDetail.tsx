import { useRef } from "react"
import { useParams } from "react-router-dom"
import { Clock, Trash2 } from "lucide-react"
import { useJob, useStatus, useEventStream } from "@/services/api/hooks"
import { LogViewer, type LogViewerHandle } from "@/components/LogViewer"
import { DetailHeader } from "@/components/detail/DetailHeader"
import { ServiceControls } from "@/components/detail/ServiceControls"
import { SystemdPanel } from "@/components/detail/SystemdPanel"
import { ConfigPanel } from "@/components/detail/ConfigPanel"

export function ScheduledDetailPage() {
  useEventStream()
  const logRef = useRef<LogViewerHandle>(null)
  const { name } = useParams<{ name: string }>()
  const { data: component, isLoading, error, refetch } = useJob(name ?? "")
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
        behavior="tool"
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
