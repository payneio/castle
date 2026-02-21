import { Link } from "react-router-dom"
import { Terminal } from "lucide-react"
import type { ToolSummary } from "@/types"
import { runnerLabel } from "@/lib/labels"

interface ToolCardProps {
  tool: ToolSummary
}

export function ToolCard({ tool }: ToolCardProps) {
  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5">
      <div className="flex items-start justify-between mb-2">
        <Link
          to={`/${tool.id}`}
          className="text-base font-semibold hover:text-[var(--primary)] transition-colors"
        >
          {tool.id}
        </Link>
        {tool.installed && (
          <span className="text-xs px-2 py-0.5 rounded bg-green-900/30 text-green-400 border border-green-800">
            installed
          </span>
        )}
      </div>

      {tool.description && (
        <p className="text-sm text-[var(--muted)] mb-3">{tool.description}</p>
      )}

      <div className="flex items-center gap-3 text-xs text-[var(--muted)] mb-3">
        {tool.runner && (
          <span className="flex items-center gap-1">
            <Terminal size={12} />
            {runnerLabel(tool.runner)}
          </span>
        )}
        {tool.version && (
          <span className="font-mono">v{tool.version}</span>
        )}
      </div>

      {tool.system_dependencies.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {tool.system_dependencies.map((dep) => (
            <span
              key={dep}
              className="text-xs px-2 py-0.5 rounded bg-amber-900/30 text-amber-400 border border-amber-800"
            >
              {dep}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
