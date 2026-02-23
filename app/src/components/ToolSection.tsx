import { useMemo } from "react"
import { Link } from "react-router-dom"
import { Download, Trash2 } from "lucide-react"
import type { ComponentSummary } from "@/types"
import { useToolAction } from "@/services/api/hooks"
import { SectionHeader } from "./SectionHeader"
import { SortHeader, useSort } from "./SortHeader"

type ToolSortKey = "id" | "status"

function statusRank(installed: boolean | null): number {
  if (installed === false) return 0
  if (installed === true) return 1
  return 2
}

interface ToolSectionProps {
  tools: ComponentSummary[]
}

export function ToolSection({ tools }: ToolSectionProps) {
  const { sortKey, sortDir, toggleSort } = useSort<ToolSortKey>("id")

  const sorted = useMemo(() => {
    const dir = sortDir === "asc" ? 1 : -1
    return [...tools].sort((a, b) => {
      switch (sortKey) {
        case "id":
          return dir * a.id.localeCompare(b.id)
        case "status":
          return dir * (statusRank(a.installed) - statusRank(b.installed))
        default:
          return 0
      }
    })
  }, [tools, sortKey, sortDir])

  return (
    <section>
      <SectionHeader category="tool" />
      <div className="border border-[var(--border)] rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-[var(--card)] border-b border-[var(--border)] text-left">
              <SortHeader label="Name" sortKey="id" current={sortKey} dir={sortDir} onSort={toggleSort} />
              <th className="px-3 py-2 font-medium text-[var(--muted)]">Description</th>
              <SortHeader label="Status" sortKey="status" current={sortKey} dir={sortDir} onSort={toggleSort} />
              <th className="px-3 py-2 font-medium text-[var(--muted)]">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((tool) => (
              <ToolRow key={tool.id} tool={tool} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function ToolRow({ tool }: { tool: ComponentSummary }) {
  const { mutate, isPending } = useToolAction()

  return (
    <tr className="border-b border-[var(--border)] last:border-b-0 hover:bg-[var(--card)]/50 transition-colors">
      <td className="px-3 py-2.5">
        <Link
          to={`/component/${tool.id}`}
          className="font-medium hover:text-[var(--primary)] transition-colors"
        >
          {tool.id}
        </Link>
      </td>
      <td className="px-3 py-2.5 text-[var(--muted)] truncate max-w-xs">
        {tool.description ?? "—"}
      </td>
      <td className="px-3 py-2.5">
        {tool.installed !== null ? (
          tool.installed ? (
            <span className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-full bg-green-900/40 text-green-400 border border-green-800/50">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
              installed
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-full bg-zinc-800/40 text-[var(--muted)] border border-[var(--border)]">
              <span className="w-1.5 h-1.5 rounded-full bg-zinc-500" />
              not installed
            </span>
          )
        ) : (
          <span className="text-[var(--muted)]">—</span>
        )}
      </td>
      <td className="px-3 py-2.5">
        {tool.installed !== null && (
          tool.installed ? (
            <button
              onClick={() => mutate({ name: tool.id, action: "uninstall" })}
              disabled={isPending}
              className="p-1 rounded hover:bg-red-800/30 text-red-400 transition-colors disabled:opacity-40"
              title="Uninstall from PATH"
            >
              <Trash2 size={14} />
            </button>
          ) : (
            <button
              onClick={() => mutate({ name: tool.id, action: "install" })}
              disabled={isPending}
              className="p-1 rounded hover:bg-green-800/30 text-green-400 transition-colors disabled:opacity-40"
              title="Install to PATH"
            >
              <Download size={14} />
            </button>
          )
        )}
      </td>
    </tr>
  )
}
