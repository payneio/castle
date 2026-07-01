import { useGateway, useStatus } from "@/services/api/hooks"
import { GatewayPanel } from "@/components/GatewayPanel"
import { PageHeader } from "@/components/PageHeader"

export function GatewayPage() {
  const { data: gateway, isLoading } = useGateway()
  const { data: statusResp } = useStatus()
  const statuses = statusResp?.statuses ?? []

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <PageHeader title="Gateway" subtitle="Reverse proxy and routes" />

      {isLoading ? (
        <p className="text-[var(--muted)]">Loading...</p>
      ) : gateway ? (
        <GatewayPanel gateway={gateway} statuses={statuses} />
      ) : (
        <p className="text-[var(--muted)]">Gateway unavailable.</p>
      )}
    </div>
  )
}
