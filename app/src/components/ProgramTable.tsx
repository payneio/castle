import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react"
import type { ProgramSummary } from "@/types"
import { BehaviorBadge } from "./BehaviorBadge"
import { StackBadge } from "./StackBadge"
import { ProgramActions } from "./ProgramActions"

interface ProgramTableProps {
  programs: ProgramSummary[]
}

type SortKey = "id" | "stack" | "behavior"
type SortDir = "asc" | "desc"

export function ProgramTable({ programs }: ProgramTableProps) {
  const [search, setSearch] = useState("")
  const [sortKey, setSortKey] = useState<SortKey>("id")
  const [sortDir, setSortDir] = useState<SortDir>("asc")

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir("asc")
    }
  }

  const filtered = useMemo(() => {
    if (!search) return programs
    const q = search.toLowerCase()
    return programs.filter(
      (c) =>
        c.id.toLowerCase().includes(q) ||
        (c.description?.toLowerCase().includes(q) ?? false),
    )
  }, [programs, search])

  const sorted = useMemo(() => {
    const dir = sortDir === "asc" ? 1 : -1
    return [...filtered].sort((a, b) => {
      switch (sortKey) {
        case "id":
          return dir * a.id.localeCompare(b.id)
        case "stack":
          return dir * (a.stack ?? "").localeCompare(b.stack ?? "")
        case "behavior":
          return dir * (a.behavior ?? "").localeCompare(b.behavior ?? "")
        default:
          return 0
      }
    })
  }, [filtered, sortKey, sortDir])

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

      <div className="border border-[var(--border)] rounded-lg overflow-x-auto">
        <table className="w-full min-w-[36rem] text-sm">
          <thead>
            <tr className="bg-[var(--card)] border-b border-[var(--border)] text-left">
              <SortHeader label="Name" sortKey="id" current={sortKey} dir={sortDir} onSort={toggleSort} />
              <SortHeader label="Stack" sortKey="stack" current={sortKey} dir={sortDir} onSort={toggleSort} />
              <SortHeader label="Behavior" sortKey="behavior" current={sortKey} dir={sortDir} onSort={toggleSort} />
              <th className="px-3 py-2 font-medium text-[var(--muted)]">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((comp) => (
              <ProgramRow key={comp.id} program={comp} />
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-6 text-center text-[var(--muted)]">
                  No programs match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function SortHeader({
  label,
  sortKey,
  current,
  dir,
  onSort,
}: {
  label: string
  sortKey: SortKey
  current: SortKey
  dir: SortDir
  onSort: (key: SortKey) => void
}) {
  const active = current === sortKey
  const Icon = active ? (dir === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown
  return (
    <th className="px-3 py-2 font-medium text-[var(--muted)]">
      <button
        onClick={() => onSort(sortKey)}
        className="flex items-center gap-1 hover:text-[var(--foreground)] transition-colors"
      >
        {label}
        <Icon size={12} className={active ? "text-[var(--foreground)]" : ""} />
      </button>
    </th>
  )
}

function ProgramRow({ program }: { program: ProgramSummary }) {
  return (
    <tr className="border-b border-[var(--border)] last:border-b-0 hover:bg-[var(--card)]/50 transition-colors">
      <td className="px-3 py-2.5">
        <Link
          to={`/programs/${program.id}`}
          className="font-medium hover:text-[var(--primary)] transition-colors"
        >
          {program.id}
        </Link>
        {program.description && (
          <p className="text-xs text-[var(--muted)] mt-0.5 truncate max-w-xs">
            {program.description}
          </p>
        )}
      </td>
      <td className="px-3 py-2.5">
        <StackBadge stack={program.stack} />
      </td>
      <td className="px-3 py-2.5">
        <BehaviorBadge behavior={program.behavior} />
      </td>
      <td className="px-3 py-2.5">
        <ProgramActions
          name={program.id}
          actions={program.actions}
          active={program.active}
          behavior={program.behavior}
          deployedAs={[...program.services, ...program.jobs]}
          compact
        />
      </td>
    </tr>
  )
}
