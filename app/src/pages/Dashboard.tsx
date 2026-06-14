import { useState } from "react"
import { Plus } from "lucide-react"
import { useServices, useJobs, usePrograms, useStatus, useGateway, useNodes, useMeshStatus, useEventStream } from "@/services/api/hooks"
import { GatewayPanel } from "@/components/GatewayPanel"
import { MeshPanel } from "@/components/MeshPanel"
import { NodeBar } from "@/components/NodeBar"
import { ServiceSection } from "@/components/ServiceSection"
import { ScheduledSection } from "@/components/ScheduledSection"
import { ProgramTable } from "@/components/ProgramTable"
import { SectionHeader } from "@/components/SectionHeader"
import { CreateDeploymentForm } from "@/components/detail/CreateDeploymentForm"


export function Dashboard() {
  useEventStream()
  const { data: services, isLoading: loadingServices } = useServices()
  const { data: jobs, isLoading: loadingJobs } = useJobs()
  const { data: programs, isLoading: loadingPrograms } = usePrograms()
  const { data: statusResp } = useStatus()
  const { data: gateway } = useGateway()
  const { data: nodes } = useNodes()
  const { data: mesh } = useMeshStatus()
  const [creating, setCreating] = useState<"service" | "job" | null>(null)

  const statuses = statusResp?.statuses ?? []
  const isLoading = loadingServices || loadingJobs || loadingPrograms
  const existing =
    creating === "service"
      ? (services ?? []).map((s) => s.id)
      : (jobs ?? []).map((j) => j.id)

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold">Castle</h1>
        <p className="text-[var(--muted)] mt-1">Personal software platform</p>
      </div>

      {nodes && <NodeBar nodes={nodes} />}

      {gateway && (
        <div className="mb-6">
          <GatewayPanel gateway={gateway} statuses={statuses} />
        </div>
      )}

      {mesh && (
        <div className="mb-10">
          <MeshPanel mesh={mesh} />
        </div>
      )}

      <div className="flex items-center gap-2 mb-6">
        <button
          onClick={() => setCreating(creating === "service" ? null : "service")}
          className="flex items-center gap-1 px-3 py-1.5 text-sm rounded border border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--primary)] transition-colors"
        >
          <Plus size={14} /> Add service
        </button>
        <button
          onClick={() => setCreating(creating === "job" ? null : "job")}
          className="flex items-center gap-1 px-3 py-1.5 text-sm rounded border border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--primary)] transition-colors"
        >
          <Plus size={14} /> Add job
        </button>
      </div>
      {creating && (
        <div className="mb-6 max-w-2xl">
          <CreateDeploymentForm
            kind={creating}
            existingNames={existing}
            onCancel={() => setCreating(null)}
          />
        </div>
      )}

      {isLoading ? (
        <p className="text-[var(--muted)]">Loading...</p>
      ) : (
        <div className="space-y-10">
          {services && services.length > 0 && (
            <ServiceSection services={services} statuses={statuses} />
          )}
          {jobs && jobs.length > 0 && (
            <ScheduledSection jobs={jobs} statuses={statuses} />
          )}
          {programs && programs.length > 0 && (
            <section>
              <SectionHeader section="program" />
              <ProgramTable programs={programs} />
            </section>
          )}
        </div>
      )}
    </div>
  )
}
