import { useState } from "react"
import { Plus } from "lucide-react"
import { useJobs, useStatus } from "@/services/api/hooks"
import { ScheduledSection } from "@/components/ScheduledSection"
import { PageHeader } from "@/components/PageHeader"
import { CreateDeploymentForm } from "@/components/detail/CreateDeploymentForm"

export function Scheduled() {
  const { data: jobs, isLoading } = useJobs()
  const { data: statusResp } = useStatus()
  const [creating, setCreating] = useState(false)

  const statuses = statusResp?.statuses ?? []
  const existing = (jobs ?? []).map((j) => j.id)

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <PageHeader
        title="Scheduled"
        subtitle="Systemd timers"
        actions={
          <button
            onClick={() => setCreating((c) => !c)}
            className="flex items-center gap-1 px-3 py-1.5 text-sm rounded border border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--primary)] transition-colors"
          >
            <Plus size={14} /> Add job
          </button>
        }
      />

      {creating && (
        <div className="mb-6 max-w-2xl">
          <CreateDeploymentForm
            kind="job"
            existingNames={existing}
            onCancel={() => setCreating(false)}
          />
        </div>
      )}

      {isLoading ? (
        <p className="text-[var(--muted)]">Loading...</p>
      ) : jobs && jobs.length > 0 ? (
        <ScheduledSection jobs={jobs} statuses={statuses} />
      ) : (
        <p className="text-[var(--muted)]">No scheduled jobs yet.</p>
      )}
    </div>
  )
}
