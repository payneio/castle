import { useMemo, useState } from "react"
import type { ProgramSummary } from "@/types"
import { ProgramCard } from "./ProgramCard"

interface ProgramListProps {
  programs: ProgramSummary[]
  linkBase?: string // where each card links (default "/programs")
  showDeployments?: boolean // list each program's deployments on the card (default true)
}

export function ProgramList({ programs, linkBase, showDeployments }: ProgramListProps) {
  const [search, setSearch] = useState("")

  const filtered = useMemo(() => {
    let base = [...programs].sort((a, b) => a.id.localeCompare(b.id))
    if (search) {
      const q = search.toLowerCase()
      base = base.filter(
        (c) =>
          c.id.toLowerCase().includes(q) ||
          (c.description?.toLowerCase().includes(q) ?? false),
      )
    }
    return base
  }, [programs, search])

  return (
    <div>
      <div className="mb-4">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter programs..."
          className="bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--primary)] w-56"
        />
      </div>

      {filtered.length === 0 ? (
        <p className="text-[var(--muted)]">No programs match.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((program) => (
            <ProgramCard
              key={program.id}
              program={program}
              linkBase={linkBase}
              showDeployments={showDeployments}
            />
          ))}
        </div>
      )}
    </div>
  )
}
