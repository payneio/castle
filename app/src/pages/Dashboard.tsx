import { useMemo } from "react"
import { useComponents, useStatus, useGateway, useNodes, useMeshStatus, useEventStream } from "@/services/api/hooks"
import { GatewayPanel } from "@/components/GatewayPanel"
import { MeshPanel } from "@/components/MeshPanel"
import { NodeBar } from "@/components/NodeBar"
import { ServiceSection } from "@/components/ServiceSection"
import { ScheduledSection } from "@/components/ScheduledSection"
import { ComponentTable } from "@/components/ComponentTable"
import { SectionHeader } from "@/components/SectionHeader"


export function Dashboard() {
  useEventStream()
  const { data: components, isLoading } = useComponents()
  const { data: statusResp } = useStatus()
  const { data: gateway } = useGateway()
  const { data: nodes } = useNodes()
  const { data: mesh } = useMeshStatus()

  const { services, scheduled } = useMemo(() => {
    const svc = (components ?? []).filter((c) => c.managed && !c.schedule)
    const sch = (components ?? []).filter((c) => c.managed && c.schedule)
    return { services: svc, scheduled: sch }
  }, [components])

  const statuses = statusResp?.statuses ?? []

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

      {isLoading ? (
        <p className="text-[var(--muted)]">Loading...</p>
      ) : (
        <div className="space-y-10">
          {services.length > 0 && (
            <ServiceSection services={services} statuses={statuses} />
          )}
          {scheduled.length > 0 && (
            <ScheduledSection jobs={scheduled} statuses={statuses} />
          )}
          {(components ?? []).length > 0 && (
            <section>
              <SectionHeader section="component" />
              <ComponentTable components={components ?? []} statuses={statuses} />
            </section>
          )}
        </div>
      )}
    </div>
  )
}
