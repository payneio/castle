import { useState } from "react"
import { Link } from "react-router-dom"
import { Server, Clock, Plus } from "lucide-react"
import type { ProgramDetail } from "@/types"
import { useServices, useJobs } from "@/services/api/hooks"
import { CreateDeploymentForm, type CreatePrefill } from "./CreateDeploymentForm"

/** The services and jobs that deploy a program. A program → 0-N services and
 * 0-N jobs; these are convenience links, not ownership (a deployment can run
 * anything, program-backed or not). The Create buttons just prefill the
 * standalone create form with sensible values. */
export function DeploymentsSection({ program }: { program: ProgramDetail }) {
  const { services, jobs, behavior } = program
  const none = services.length === 0 && jobs.length === 0
  const [creating, setCreating] = useState<"service" | "job" | null>(null)

  const { data: allServices } = useServices()
  const { data: allJobs } = useJobs()
  const existing =
    creating === "service"
      ? (allServices ?? []).map((s) => s.id)
      : (allJobs ?? []).map((j) => j.id)

  const prefill: CreatePrefill = {
    name: program.id,
    program: program.id,
    runTarget: program.id,
    runner: program.stack?.startsWith("python") || !program.stack ? "python" : "command",
  }

  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider">
          Deployments
        </h2>
        <div className="flex gap-2">
          <button
            onClick={() => setCreating(creating === "service" ? null : "service")}
            className="flex items-center gap-1 text-xs text-[var(--primary)] hover:underline"
          >
            <Plus size={12} /> Create service
          </button>
          <button
            onClick={() => setCreating(creating === "job" ? null : "job")}
            className="flex items-center gap-1 text-xs text-[var(--primary)] hover:underline"
          >
            <Plus size={12} /> Create job
          </button>
        </div>
      </div>
      <p className="text-xs text-[var(--muted)] mb-4">
        Services and jobs that run this program.
      </p>

      {creating && (
        <CreateDeploymentForm
          kind={creating}
          prefill={prefill}
          existingNames={existing}
          onCancel={() => setCreating(null)}
        />
      )}

      {none && !creating ? (
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
