import { useMemo } from "react"
import { Link } from "react-router-dom"
import { RefreshCw } from "lucide-react"
import type { ComponentSummary } from "@/types"
import { useServiceAction } from "@/services/api/hooks"
import { SectionHeader } from "./SectionHeader"
import { SortHeader, useSort } from "./SortHeader"

type JobSortKey = "id" | "timer"

interface JobSectionProps {
  jobs: ComponentSummary[]
}

export function JobSection({ jobs }: JobSectionProps) {
  const { sortKey, sortDir, toggleSort } = useSort<JobSortKey>("id")

  const sorted = useMemo(() => {
    const dir = sortDir === "asc" ? 1 : -1
    return [...jobs].sort((a, b) => {
      switch (sortKey) {
        case "id":
          return dir * a.id.localeCompare(b.id)
        case "timer": {
          const aTimer = a.systemd?.timer ? 1 : 0
          const bTimer = b.systemd?.timer ? 1 : 0
          return dir * (aTimer - bTimer)
        }
        default:
          return 0
      }
    })
  }, [jobs, sortKey, sortDir])

  return (
    <section>
      <SectionHeader category="job" />
      <div className="border border-[var(--border)] rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-[var(--card)] border-b border-[var(--border)] text-left">
              <SortHeader label="Name" sortKey="id" current={sortKey} dir={sortDir} onSort={toggleSort} />
              <th className="px-3 py-2 font-medium text-[var(--muted)]">Schedule</th>
              <SortHeader label="Timer" sortKey="timer" current={sortKey} dir={sortDir} onSort={toggleSort} />
              <th className="px-3 py-2 font-medium text-[var(--muted)]">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((job) => (
              <JobRow key={job.id} job={job} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function JobRow({ job }: { job: ComponentSummary }) {
  const { mutate, isPending } = useServiceAction()
  const hasTimer = job.systemd?.timer ?? false

  return (
    <tr className="border-b border-[var(--border)] last:border-b-0 hover:bg-[var(--card)]/50 transition-colors">
      <td className="px-3 py-2.5">
        <Link
          to={`/component/${job.id}`}
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
      <td className="px-3 py-2.5 font-mono text-[var(--muted)]">
        {job.schedule ?? "—"}
      </td>
      <td className="px-3 py-2.5">
        {hasTimer ? (
          <span className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-full bg-purple-900/40 text-purple-400 border border-purple-800/50">
            <span className="w-1.5 h-1.5 rounded-full bg-purple-400" />
            active
          </span>
        ) : (
          <span className="text-[var(--muted)]">—</span>
        )}
      </td>
      <td className="px-3 py-2.5">
        {job.managed && (
          <button
            onClick={() => mutate({ name: job.id, action: "restart" })}
            disabled={isPending}
            className="p-1 rounded hover:bg-blue-800/30 text-blue-400 transition-colors disabled:opacity-40"
            title="Restart"
          >
            <RefreshCw size={14} />
          </button>
        )}
      </td>
    </tr>
  )
}
