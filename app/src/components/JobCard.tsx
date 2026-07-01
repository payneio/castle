import { Clock, Play, RefreshCw, Square, Terminal } from "lucide-react"
import { Link } from "react-router-dom"
import type { JobSummary, HealthStatus } from "@/types"
import { useServiceAction } from "@/services/api/hooks"
import { runnerLabel } from "@/lib/labels"
import { StackBadge } from "./StackBadge"

interface JobCardProps {
  job: JobSummary
  health?: HealthStatus
}

export function JobCard({ job, health }: JobCardProps) {
  const { mutate, isPending } = useServiceAction()
  const isDown = health?.status === "down"

  const doAction = (action: string) => {
    mutate({ name: job.id, action })
  }

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
          {job.runner && (
            <span className="flex items-center gap-1">
              <Terminal size={12} />
              {runnerLabel(job.runner)}
            </span>
          )}
        </div>

        {job.managed && (
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
