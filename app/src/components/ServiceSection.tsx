import { useMemo } from "react"
import type { ServiceSummary, HealthStatus } from "@/types"
import { ServiceCard } from "./ServiceCard"

interface ServiceSectionProps {
  services: ServiceSummary[]
  statuses: HealthStatus[]
}

export function ServiceSection({ services, statuses }: ServiceSectionProps) {
  const statusMap = useMemo(() => new Map(statuses.map((s) => [s.id, s])), [statuses])

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {services.map((svc) => (
        <ServiceCard key={svc.id} service={svc} health={statusMap.get(svc.id)} />
      ))}
    </div>
  )
}
