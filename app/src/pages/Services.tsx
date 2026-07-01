import { useState } from "react"
import { Plus } from "lucide-react"
import { useServices, useStatus } from "@/services/api/hooks"
import { ServiceSection } from "@/components/ServiceSection"
import { PageHeader } from "@/components/PageHeader"
import { CreateDeploymentForm } from "@/components/detail/CreateDeploymentForm"

export function Services() {
  const { data: services, isLoading } = useServices()
  const { data: statusResp } = useStatus()
  const [creating, setCreating] = useState(false)

  const statuses = statusResp?.statuses ?? []
  const existing = (services ?? []).map((s) => s.id)

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <PageHeader
        title="Services"
        subtitle="Long-running & served — systemd daemons and caddy statics"
        actions={
          <button
            onClick={() => setCreating((c) => !c)}
            className="flex items-center gap-1 px-3 py-1.5 text-sm rounded border border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--primary)] transition-colors"
          >
            <Plus size={14} /> Add service
          </button>
        }
      />

      {creating && (
        <div className="mb-6 max-w-2xl">
          <CreateDeploymentForm
            kind="service"
            existingNames={existing}
            onCancel={() => setCreating(false)}
          />
        </div>
      )}

      {isLoading ? (
        <p className="text-[var(--muted)]">Loading...</p>
      ) : services && services.length > 0 ? (
        <ServiceSection services={services} statuses={statuses} />
      ) : (
        <p className="text-[var(--muted)]">No services yet.</p>
      )}
    </div>
  )
}
