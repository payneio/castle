import { useState } from "react"
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react"

export type SortDir = "asc" | "desc"

export function SortHeader<K extends string>({
  label,
  sortKey,
  current,
  dir,
  onSort,
}: {
  label: string
  sortKey: K
  current: K
  dir: SortDir
  onSort: (key: K) => void
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

export function useSort<K extends string>(defaultKey: K, defaultDir: SortDir = "asc") {
  const [sortKey, setSortKey] = useState<K>(defaultKey)
  const [sortDir, setSortDir] = useState<SortDir>(defaultDir)

  const toggleSort = (key: K) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir("asc")
    }
  }

  return { sortKey, sortDir, toggleSort } as const
}
