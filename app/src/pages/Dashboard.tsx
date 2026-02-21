import { ComponentTable } from "@/components/ComponentTable"
import { useComponents, useStatus, useGateway, useEventStream } from "@/services/api/hooks"

export function Dashboard() {
  useEventStream()
  const { data: components, isLoading } = useComponents()
  const { data: statusResp } = useStatus()
  const { data: gateway } = useGateway()

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold">Castle</h1>
        <p className="text-[var(--muted)] mt-1">
          Personal software platform
          {gateway && (
            <span className="ml-2 text-sm">
              &middot; {gateway.component_count} components &middot; port {gateway.port}
            </span>
          )}
        </p>
      </div>

      {isLoading ? (
        <p className="text-[var(--muted)]">Loading components...</p>
      ) : components ? (
        <ComponentTable
          components={components}
          statuses={statusResp?.statuses ?? []}
        />
      ) : (
        <p className="text-red-400">Failed to load components</p>
      )}
    </div>
  )
}
