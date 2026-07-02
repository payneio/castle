import { Clock, Power, RefreshCw, Terminal } from "lucide-react"
import { Link } from "react-router-dom"
import type { JobSummary, HealthStatus } from "@/types"
import { useServiceAction, useSetEnabled } from "@/services/api/hooks"
import { launcherLabel } from "@/lib/labels"
import { StackBadge } from "./StackBadge"

interface JobCardProps {
  job: JobSummary
  health?: HealthStatus
}

export function JobCard({ job, health }: JobCardProps) {
  const restart = useServiceAction()
  const setEnabled = useSetEnabled()
  const busy = restart.isPending || setEnabled.isPending

  return (
    <div className="relative bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 hover:border-[var(--primary)] transition-colors">
      <div className="flex items-start justify-between mb-2">
        <Link
          to={`/jobs/${job.id}`}
          className="text-base font-semibold hover:text-[var(--primary)] transition-colors after:absolute after:inset-0"
        >
          {job.id}
        </Link>
        {health && (
          <span className={`text-xs ${health.status === "up" ? "text-green-400" : "text-red-400"}`}>
            {health.status}
          </span>
        )}
      </div>

      <div className="flex gap-1.5 mb-2">
        <StackBadge stack={job.stack} />
      </div>

      {job.description && (
        <p className="text-sm text-[var(--muted)] mb-3">{job.description}</p>
      )}

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 text-xs text-[var(--muted)]">
          {job.schedule && (
            <span className="flex items-center gap-1 font-mono">
              <Clock size={12} />
              {job.schedule}
            </span>
          )}
          {job.launcher && (
            <span className="flex items-center gap-1">
              <Terminal size={12} />
              {launcherLabel(job.launcher)}
            </span>
          )}
        </div>

        {job.managed && (
          <div className="relative z-10 flex items-center gap-1">
            <button
              onClick={() => setEnabled.mutate({ name: job.id, enabled: !job.enabled })}
              disabled={busy}
              className={`p-1 rounded transition-colors disabled:opacity-40 ${
                job.enabled
                  ? "hover:bg-red-800/30 text-red-400"
                  : "hover:bg-green-800/30 text-green-400"
              }`}
              title={job.enabled ? "Disable" : "Enable"}
            >
              <Power size={14} />
            </button>
            {job.enabled && (
              <button
                onClick={() => restart.mutate({ name: job.id, action: "restart" })}
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
