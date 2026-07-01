import { useState } from "react"
import { Link } from "react-router-dom"
import { Plus, ChevronRight } from "lucide-react"
import type { ProgramDetail } from "@/types"
import { useServices, useJobs } from "@/services/api/hooks"
import { KindBadge } from "@/components/KindBadge"
import { CreateDeploymentForm, type CreatePrefill } from "./CreateDeploymentForm"

/** How a program is deployed. A program → 0-N deployments; each row links to its
 * detail page (where its config + lifecycle live). tool → /tools, static/service
 * → /services, job → /jobs. */
export function DeploymentsSection({ program }: { program: ProgramDetail }) {
  const { deployments } = program
  const [creating, setCreating] = useState(false)

  const { data: allServices } = useServices()
  const { data: allJobs } = useJobs()
  const existing = [
    ...(allServices ?? []).map((s) => s.id),
    ...(allJobs ?? []).map((j) => j.id),
  ]

  const prefill: CreatePrefill = {
    name: program.id,
    program: program.id,
    runTarget: program.id,
    launcher: program.stack?.startsWith("python") || !program.stack ? "python" : "command",
  }

  const detailPath = (name: string, kind: string) =>
    kind === "tool" ? `/tools/${name}` : kind === "job" ? `/jobs/${name}` : `/services/${name}`

  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider">
          Deployments
        </h2>
        <button
          onClick={() => setCreating((c) => !c)}
          className="flex items-center gap-1 text-xs text-[var(--primary)] hover:underline"
        >
          <Plus size={12} /> Add deployment
        </button>
      </div>
      <p className="text-xs text-[var(--muted)] mb-4">
        How this program is materialized into the runtime.
      </p>

      {creating && (
        <CreateDeploymentForm
          prefill={prefill}
          existingNames={existing}
          onCancel={() => setCreating(false)}
        />
      )}

      {deployments.length === 0 && !creating ? (
        <p className="text-sm text-[var(--muted)]">No deployment yet.</p>
      ) : (
        <div className="space-y-1">
          {deployments.map((d) => (
            <Link
              key={d.name}
              to={detailPath(d.name, d.kind)}
              className="flex items-center gap-2 rounded px-2 py-1.5 -mx-2 text-sm hover:bg-black/20 transition-colors group"
            >
              <span className="font-mono">{d.name}</span>
              <KindBadge kind={d.kind} />
              <ChevronRight
                size={14}
                className="ml-auto text-[var(--muted)] group-hover:text-[var(--primary)]"
              />
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
