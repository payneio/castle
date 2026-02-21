import { Link } from "react-router-dom"
import { Settings } from "lucide-react"
import { ComponentGrid } from "@/components/ComponentGrid"
import { useComponents, useStatus, useGateway, useEventStream } from "@/services/api/hooks"

export function Dashboard() {
  useEventStream()
  const { data: components, isLoading } = useComponents()
  const { data: statusResp } = useStatus()
  const { data: gateway } = useGateway()

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <div className="flex items-start justify-between mb-8">
        <div>
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
        <Link
          to="/config"
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded bg-[var(--border)] hover:bg-gray-600 text-[var(--foreground)] transition-colors"
        >
          <Settings size={14} /> Config
        </Link>
      </div>

      {isLoading ? (
        <p className="text-[var(--muted)]">Loading components...</p>
      ) : components ? (
        <ComponentGrid
          components={components}
          statuses={statusResp?.statuses ?? []}
        />
      ) : (
        <p className="text-red-400">Failed to load components</p>
      )}
    </div>
  )
}
