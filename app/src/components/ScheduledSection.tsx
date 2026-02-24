import { Link } from "react-router-dom"
import { Play, RefreshCw, Square } from "lucide-react"
import type { JobSummary, HealthStatus } from "@/types"
import { useServiceAction } from "@/services/api/hooks"
import { SectionHeader } from "./SectionHeader"
import { StackBadge } from "./StackBadge"

interface ScheduledSectionProps {
  jobs: JobSummary[]
  statuses: HealthStatus[]
}

export function ScheduledSection({ jobs, statuses }: ScheduledSectionProps) {
  const statusMap = new Map(statuses.map((s) => [s.id, s]))

  return (
    <section>
      <SectionHeader section="scheduled" />
      <div className="border border-[var(--border)] rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-[var(--card)] border-b border-[var(--border)] text-left">
              <th className="px-3 py-2 font-medium text-[var(--muted)]">Name</th>
              <th className="px-3 py-2 font-medium text-[var(--muted)]">Schedule</th>
              <th className="px-3 py-2 font-medium text-[var(--muted)]">Stack</th>
              <th className="px-3 py-2 font-medium text-[var(--muted)]">Status</th>
              <th className="px-3 py-2 font-medium text-[var(--muted)]">Actions</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <ScheduledRow key={job.id} job={job} health={statusMap.get(job.id)} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function ScheduledRow({ job, health }: { job: JobSummary; health?: HealthStatus }) {
  const { mutate, isPending } = useServiceAction()
  const isDown = health?.status === "down"

  return (
    <tr className="border-b border-[var(--border)] last:border-b-0 hover:bg-[var(--card)]/50 transition-colors">
      <td className="px-3 py-2.5">
        <Link
          to={`/jobs/${job.id}`}
          className="font-medium hover:text-[var(--primary)] transition-colors"
        >
          {job.id}
        </Link>
        {job.description && (
          <p className="text-xs text-[var(--muted)] mt-0.5 truncate max-w-xs">
            {job.description}
          </p>
        )}
      </td>
      <td className="px-3 py-2.5 font-mono text-xs">{job.schedule}</td>
      <td className="px-3 py-2.5">
        <StackBadge stack={job.stack} />
      </td>
      <td className="px-3 py-2.5">
        {health ? (
          <span className={`text-xs ${health.status === "up" ? "text-green-400" : "text-red-400"}`}>
            {health.status}
          </span>
        ) : (
          <span className="text-[var(--muted)]">—</span>
        )}
      </td>
      <td className="px-3 py-2.5">
        <div className="flex items-center gap-1">
          {isDown && (
            <button
              onClick={() => mutate({ name: job.id, action: "start" })}
              disabled={isPending}
              className="p-1 rounded hover:bg-green-800/30 text-green-400 transition-colors disabled:opacity-40"
              title="Start"
            >
              <Play size={14} />
            </button>
          )}
          <button
            onClick={() => mutate({ name: job.id, action: "restart" })}
            disabled={isPending}
            className="p-1 rounded hover:bg-blue-800/30 text-blue-400 transition-colors disabled:opacity-40"
            title="Restart"
          >
            <RefreshCw size={14} />
          </button>
          {!isDown && (
            <button
              onClick={() => mutate({ name: job.id, action: "stop" })}
              disabled={isPending}
              className="p-1 rounded hover:bg-red-800/30 text-red-400 transition-colors disabled:opacity-40"
              title="Stop"
            >
              <Square size={14} />
            </button>
          )}
        </div>
      </td>
    </tr>
  )
}
