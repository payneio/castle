import { useMemo, useState } from "react"
import type { ProgramSummary } from "@/types"
import { ProgramCard } from "./ProgramCard"
import { kindLabel } from "@/lib/labels"
import { cn } from "@/lib/utils"

interface ProgramListProps {
  programs: ProgramSummary[]
  linkBase?: string // where each card links (default "/programs")
  showDeployments?: boolean // list each program's deployments on the card (default true)
  filterable?: boolean // show deployment-kind filter chips (default false)
}

const KIND_ORDER = ["service", "job", "tool", "static", "reference"]

// Active chip color per kind — mirrors KindBadge so the filter reads as the badge.
const KIND_ACTIVE: Record<string, string> = {
  service: "bg-green-700 text-white border-green-600",
  job: "bg-purple-700 text-white border-purple-600",
  tool: "bg-blue-700 text-white border-blue-600",
  static: "bg-cyan-700 text-white border-cyan-600",
  reference: "bg-gray-600 text-gray-200 border-gray-500",
}

export function ProgramList({ programs, linkBase, showDeployments, filterable }: ProgramListProps) {
  const [search, setSearch] = useState("")
  // Filter by a *deployment* kind: a program matches if it has a deployment of
  // this kind (so a tool-and-job program shows under both Tool and Job).
  const [kind, setKind] = useState<string | null>(null)

  // Count programs per deployment kind (a program counts once toward each kind
  // it deploys as).
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const p of programs) {
      for (const k of new Set(p.deployments.map((d) => d.kind))) {
        c[k] = (c[k] ?? 0) + 1
      }
    }
    return c
  }, [programs])
  const kindsPresent = KIND_ORDER.filter((k) => counts[k])

  const filtered = useMemo(() => {
    let base = [...programs].sort((a, b) => a.id.localeCompare(b.id))
    if (kind) base = base.filter((p) => p.deployments.some((d) => d.kind === kind))
    if (search) {
      const q = search.toLowerCase()
      base = base.filter(
        (c) =>
          c.id.toLowerCase().includes(q) ||
          (c.description?.toLowerCase().includes(q) ?? false),
      )
    }
    return base
  }, [programs, search, kind])

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter programs..."
          className="bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--primary)] w-56"
        />
        {filterable && kindsPresent.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            <Chip
              label={`All (${programs.length})`}
              active={kind === null}
              activeClass="bg-[var(--primary)] text-white border-[var(--primary)]"
              onClick={() => setKind(null)}
            />
            {kindsPresent.map((k) => (
              <Chip
                key={k}
                label={`${kindLabel(k)} (${counts[k]})`}
                active={kind === k}
                activeClass={KIND_ACTIVE[k]}
                onClick={() => setKind(kind === k ? null : k)}
              />
            ))}
          </div>
        )}
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

function Chip({
  label,
  active,
  activeClass,
  onClick,
}: {
  label: string
  active: boolean
  activeClass: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "text-xs px-2.5 py-1 rounded-full border transition-colors",
        active
          ? activeClass
          : "border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--primary)]",
      )}
    >
      {label}
    </button>
  )
}
