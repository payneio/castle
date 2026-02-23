import { useParams, Link } from "react-router-dom"
import { ArrowLeft, Server } from "lucide-react"
import { useNode } from "@/services/api/hooks"
import { RoleBadge } from "@/components/RoleBadge"
import { cn } from "@/lib/utils"

export function NodeDetailPage() {
  const { hostname } = useParams<{ hostname: string }>()
  const { data: node, isLoading, error } = useNode(hostname ?? "")

  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto px-6 py-8">
        <p className="text-[var(--muted)]">Loading...</p>
      </div>
    )
  }

  if (error || !node) {
    return (
      <div className="max-w-4xl mx-auto px-6 py-8">
        <Link to="/" className="text-[var(--muted)] hover:text-[var(--foreground)] flex items-center gap-1 mb-4">
          <ArrowLeft size={14} /> Back
        </Link>
        <p className="text-red-400">Node "{hostname}" not found.</p>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <Link to="/" className="text-[var(--muted)] hover:text-[var(--foreground)] flex items-center gap-1 mb-4">
        <ArrowLeft size={14} /> Back
      </Link>

      <div className="mb-6">
        <div className="flex items-center gap-3">
          <Server size={20} className="text-[var(--primary)]" />
          <h1 className="text-2xl font-bold">{node.hostname}</h1>
          <span
            className={cn(
              "inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full",
              node.online ? "bg-green-800/50 text-green-300" : "bg-zinc-700/50 text-zinc-400",
            )}
          >
            <span className={cn("w-1.5 h-1.5 rounded-full", node.online ? "bg-green-400" : "bg-zinc-500")} />
            {node.online ? "online" : "offline"}
          </span>
          {node.is_local && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-blue-800/50 text-blue-300">local</span>
          )}
        </div>
        <p className="text-sm text-[var(--muted)] mt-1">
          Gateway port {node.gateway_port} &middot; {node.deployed_count} deployed &middot; {node.service_count} services
        </p>
      </div>

      {/* Deployed components table */}
      {node.deployed.length > 0 ? (
        <div className="border border-[var(--border)] rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-[var(--card)] border-b border-[var(--border)] text-left">
                <th className="px-3 py-2 font-medium text-[var(--muted)]">Component</th>
                <th className="px-3 py-2 font-medium text-[var(--muted)]">Category</th>
                <th className="px-3 py-2 font-medium text-[var(--muted)]">Runner</th>
                <th className="px-3 py-2 font-medium text-[var(--muted)]">Port</th>
              </tr>
            </thead>
            <tbody>
              {node.deployed.map((comp) => (
                <tr
                  key={comp.id}
                  className="border-b border-[var(--border)] last:border-b-0 hover:bg-[var(--card)]/50 transition-colors"
                >
                  <td className="px-3 py-2.5">
                    <Link
                      to={`/component/${comp.id}`}
                      className="font-medium hover:text-[var(--primary)] transition-colors"
                    >
                      {comp.id}
                    </Link>
                    {comp.description && (
                      <p className="text-xs text-[var(--muted)] mt-0.5 truncate max-w-xs">{comp.description}</p>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    <RoleBadge role={comp.category} />
                  </td>
                  <td className="px-3 py-2.5 text-[var(--muted)]">
                    {comp.runner ?? "—"}
                  </td>
                  <td className="px-3 py-2.5 font-mono text-[var(--muted)]">
                    {comp.port ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-[var(--muted)]">No deployed components on this node.</p>
      )}
    </div>
  )
}
