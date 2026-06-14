import { Link } from "react-router-dom"
import { Server, Clock } from "lucide-react"
import type { ProgramDetail } from "@/types"

/** The services and jobs that deploy a program. A program → 0-N services and
 * 0-N jobs; these are convenience links, not ownership (a deployment can run
 * anything, program-backed or not). */
export function DeploymentsSection({ program }: { program: ProgramDetail }) {
  const { services, jobs, behavior } = program
  const none = services.length === 0 && jobs.length === 0

  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
      <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider mb-1">
        Deployments
      </h2>
      <p className="text-xs text-[var(--muted)] mb-4">
        Services and jobs that run this program.
      </p>

      {none ? (
        <p className="text-sm text-[var(--muted)]">
          {behavior === "daemon"
            ? "No service yet — this daemon isn't deployed."
            : behavior === "tool"
              ? "Not scheduled — add a job to run it on a timer."
              : "None."}
        </p>
      ) : (
        <div className="space-y-1.5">
          {services.map((s) => (
            <Link
              key={s}
              to={`/services/${s}`}
              className="flex items-center gap-2 text-sm hover:text-[var(--primary)] transition-colors"
            >
              <Server size={14} className="text-[var(--muted)]" />
              <span className="font-medium">{s}</span>
              <span className="text-xs text-[var(--muted)]">service</span>
            </Link>
          ))}
          {jobs.map((j) => (
            <Link
              key={j}
              to={`/jobs/${j}`}
              className="flex items-center gap-2 text-sm hover:text-[var(--primary)] transition-colors"
            >
              <Clock size={14} className="text-[var(--muted)]" />
              <span className="font-medium">{j}</span>
              <span className="text-xs text-[var(--muted)]">job</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
