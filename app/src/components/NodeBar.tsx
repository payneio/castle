import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"
import type { NodeSummary } from "@/types"

interface NodeBarProps {
  nodes: NodeSummary[]
}

export function NodeBar({ nodes }: NodeBarProps) {
  // Only show when there are remote nodes
  if (nodes.length <= 1) return null

  return (
    <div className="flex items-center gap-2 mb-6">
      {nodes.map((node) => (
        <Link
          key={node.hostname}
          to={`/node/${node.hostname}`}
          className={cn(
            "flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md border transition-colors",
            node.is_local
              ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--foreground)]"
              : "border-[var(--border)] bg-[var(--card)] text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--foreground)]/20",
            node.is_stale && "opacity-50",
          )}
        >
          <span
            className={cn(
              "w-2 h-2 rounded-full",
              node.online && !node.is_stale ? "bg-green-400" : "bg-zinc-500",
            )}
          />
          <span className="font-medium">{node.hostname}</span>
          {!node.is_local && node.deployed_count > 0 && (
            <span className="text-xs text-[var(--muted)]">({node.deployed_count})</span>
          )}
        </Link>
      ))}
    </div>
  )
}
