import { useMemo } from "react"
import type { ComponentSummary, HealthStatus } from "@/types"
import { ComponentCard } from "./ComponentCard"
import { SectionHeader } from "./SectionHeader"

interface ServiceSectionProps {
  services: ComponentSummary[]
  statuses: HealthStatus[]
}

export function ServiceSection({ services, statuses }: ServiceSectionProps) {
  const statusMap = useMemo(() => new Map(statuses.map((s) => [s.id, s])), [statuses])

  return (
    <section>
      <SectionHeader category="service" />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {services.map((svc) => (
          <ComponentCard key={svc.id} component={svc} health={statusMap.get(svc.id)} />
        ))}
      </div>
    </section>
  )
}
