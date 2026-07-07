import { useParams, Link } from "react-router-dom"
import { Clock, Package } from "lucide-react"
import { useJob } from "@/services/api/hooks"
import { LogViewer } from "@/components/LogViewer"
import { DetailHeader } from "@/components/detail/DetailHeader"
import { ServiceControls } from "@/components/detail/ServiceControls"
import { SystemdPanel } from "@/components/detail/SystemdPanel"
import { ConfigPanel } from "@/components/detail/ConfigPanel"
import { RelatedDeployments } from "@/components/detail/RelatedDeployments"

export function ScheduledDetailPage() {
  const { name } = useParams<{ name: string }>()
  const { data: deployment, isLoading, error, refetch } = useJob(name ?? "")

  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8 text-[var(--muted)]">Loading...</div>
    )
  }

  if (error || !deployment) {
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
        backTo="/scheduled"
        backLabel="Back to Jobs"
        name={deployment.id}
        kind="job"
        stack={deployment.stack}
        source={deployment.source}
      >
        <ServiceControls name={deployment.id} enabled={deployment.enabled} />
      </DetailHeader>

      <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          {deployment.schedule && (
            <>
              <span className="text-[var(--muted)]">Cron</span>
              <span className="flex items-center gap-2 min-w-0 break-all font-mono">
                <Clock size={14} className="shrink-0 text-[var(--muted)]" />
                {deployment.schedule}
              </span>
            </>
          )}
          {deployment.program && (
            <>
              <span className="text-[var(--muted)]">Program</span>
              <Link
                to={`/programs/${deployment.program}`}
                className="flex items-center gap-1.5 min-w-0 text-[var(--primary)] hover:underline"
              >
                <Package size={14} className="shrink-0" /> {deployment.program}
              </Link>
            </>
          )}
        </div>
      </div>

      <RelatedDeployments name={deployment.id} />

      <ConfigPanel deployment={deployment} configSection="jobs" onRefetch={refetch} />

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
