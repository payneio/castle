import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { ArrowDown, ArrowUp, ArrowUpDown, Download, Play, RefreshCw, Square, Trash2 } from "lucide-react"
import type { ComponentSummary, HealthStatus } from "@/types"
import { useServiceAction, useToolAction } from "@/services/api/hooks"
import { runnerLabel } from "@/lib/labels"
import { HealthBadge } from "./HealthBadge"
import { RoleBadge } from "./RoleBadge"

interface ComponentTableProps {
  components: ComponentSummary[]
  statuses: HealthStatus[]
}

type SortKey = "id" | "role" | "runner" | "schedule" | "port" | "status"
type SortDir = "asc" | "desc"

function statusRank(s: HealthStatus | undefined, installed: boolean | null): number {
  // Health takes priority for services
  if (s) {
    if (s.status === "down") return 0
    if (s.status === "up") return 3
    return 2
  }
  // Installed state for tools
  if (installed === false) return 1
  if (installed === true) return 3
  return 2
}

export function ComponentTable({ components, statuses }: ComponentTableProps) {
  const statusMap = useMemo(() => new Map(statuses.map((s) => [s.id, s])), [statuses])
  const allRoles = useMemo(() => {
    const set = new Set<string>()
    for (const c of components) for (const r of c.roles) set.add(r)
    return Array.from(set).sort()
  }, [components])

  const [roleFilter, setRoleFilter] = useState<string | null>(null)
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
    let list = components
    if (roleFilter) {
      list = list.filter((c) => c.roles.includes(roleFilter))
    }
    if (search) {
      const q = search.toLowerCase()
      list = list.filter(
        (c) =>
          c.id.toLowerCase().includes(q) ||
          (c.description?.toLowerCase().includes(q) ?? false),
      )
    }
    return list
  }, [components, roleFilter, search])

  const sorted = useMemo(() => {
    const dir = sortDir === "asc" ? 1 : -1
    return [...filtered].sort((a, b) => {
      switch (sortKey) {
        case "id":
          return dir * a.id.localeCompare(b.id)
        case "role":
          return dir * (a.roles[0] ?? "").localeCompare(b.roles[0] ?? "")
        case "runner":
          return dir * (a.runner ?? "").localeCompare(b.runner ?? "")
        case "schedule":
          return dir * (a.schedule ?? "").localeCompare(b.schedule ?? "")
        case "port":
          return dir * ((a.port ?? 0) - (b.port ?? 0))
        case "status":
          return dir * (statusRank(statusMap.get(a.id), a.installed) - statusRank(statusMap.get(b.id), b.installed))
        default:
          return 0
      }
    })
  }, [filtered, sortKey, sortDir, statusMap])

  return (
    <div>
      {/* Filters */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter components..."
          className="bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--primary)] w-56"
        />
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setRoleFilter(null)}
            className={`text-xs px-2 py-1 rounded transition-colors ${
              roleFilter === null
                ? "bg-[var(--primary)] text-white"
                : "bg-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            All
          </button>
          {allRoles.map((role) => (
            <button
              key={role}
              onClick={() => setRoleFilter(roleFilter === role ? null : role)}
              className={`text-xs px-2 py-1 rounded transition-colors ${
                roleFilter === role
                  ? "bg-[var(--primary)] text-white"
                  : "bg-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)]"
              }`}
            >
              {role}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="border border-[var(--border)] rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-[var(--card)] border-b border-[var(--border)] text-left">
              <SortHeader label="Name" sortKey="id" current={sortKey} dir={sortDir} onSort={toggleSort} />
              <SortHeader label="Roles" sortKey="role" current={sortKey} dir={sortDir} onSort={toggleSort} />
              <SortHeader label="Runner" sortKey="runner" current={sortKey} dir={sortDir} onSort={toggleSort} />
              <SortHeader label="Schedule" sortKey="schedule" current={sortKey} dir={sortDir} onSort={toggleSort} />
              <SortHeader label="Port" sortKey="port" current={sortKey} dir={sortDir} onSort={toggleSort} />
              <SortHeader label="Status" sortKey="status" current={sortKey} dir={sortDir} onSort={toggleSort} />
              <th className="px-3 py-2 font-medium text-[var(--muted)]">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((comp) => (
              <ComponentRow
                key={comp.id}
                component={comp}
                health={statusMap.get(comp.id)}
              />
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-[var(--muted)]">
                  No components match.
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

function InstalledBadge({ installed }: { installed: boolean }) {
  return installed ? (
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
}

function ComponentRow({
  component,
  health,
}: {
  component: ComponentSummary
  health?: HealthStatus
}) {
  const hasHttp = component.port != null
  const isTool = component.installed !== null
  const { mutate: serviceAction, isPending: servicePending } = useServiceAction()
  const { mutate: toolAction, isPending: toolPending } = useToolAction()
  const isDown = health?.status === "down"

  return (
    <tr className="border-b border-[var(--border)] last:border-b-0 hover:bg-[var(--card)]/50 transition-colors">
      <td className="px-3 py-2.5">
        <Link
          to={`/component/${component.id}`}
          className="font-medium hover:text-[var(--primary)] transition-colors"
          title={component.systemd?.unit_path ?? undefined}
        >
          {component.id}
        </Link>
        {component.description && (
          <p className="text-xs text-[var(--muted)] mt-0.5 truncate max-w-xs">
            {component.description}
          </p>
        )}
      </td>
      <td className="px-3 py-2.5">
        <div className="flex gap-1 flex-wrap">
          {component.roles.map((role) => (
            <RoleBadge key={role} role={role} />
          ))}
        </div>
      </td>
      <td className="px-3 py-2.5 text-[var(--muted)]">
        {component.runner ? runnerLabel(component.runner) : "—"}
      </td>
      <td className="px-3 py-2.5 font-mono text-[var(--muted)]">
        {component.schedule ?? "—"}
      </td>
      <td className="px-3 py-2.5 font-mono text-[var(--muted)]">
        {component.port ?? "—"}
      </td>
      <td className="px-3 py-2.5">
        {health ? (
          <HealthBadge status={health.status} latency={health.latency_ms} />
        ) : hasHttp ? (
          <HealthBadge status="unknown" />
        ) : isTool ? (
          <InstalledBadge installed={component.installed!} />
        ) : (
          <span className="text-[var(--muted)]">—</span>
        )}
      </td>
      <td className="px-3 py-2.5">
        {component.managed ? (
          <div className="flex items-center gap-1">
            {isDown && (
              <button
                onClick={() => serviceAction({ name: component.id, action: "start" })}
                disabled={servicePending}
                className="p-1 rounded hover:bg-green-800/30 text-green-400 transition-colors disabled:opacity-40"
                title="Start"
              >
                <Play size={14} />
              </button>
            )}
            <button
              onClick={() => serviceAction({ name: component.id, action: "restart" })}
              disabled={servicePending}
              className="p-1 rounded hover:bg-blue-800/30 text-blue-400 transition-colors disabled:opacity-40"
              title="Restart"
            >
              <RefreshCw size={14} />
            </button>
            {!isDown && (
              <button
                onClick={() => serviceAction({ name: component.id, action: "stop" })}
                disabled={servicePending}
                className="p-1 rounded hover:bg-red-800/30 text-red-400 transition-colors disabled:opacity-40"
                title="Stop"
              >
                <Square size={14} />
              </button>
            )}
          </div>
        ) : isTool ? (
          <div className="flex items-center gap-1">
            {component.installed ? (
              <button
                onClick={() => toolAction({ name: component.id, action: "uninstall" })}
                disabled={toolPending}
                className="p-1 rounded hover:bg-red-800/30 text-red-400 transition-colors disabled:opacity-40"
                title="Uninstall from PATH"
              >
                <Trash2 size={14} />
              </button>
            ) : (
              <button
                onClick={() => toolAction({ name: component.id, action: "install" })}
                disabled={toolPending}
                className="p-1 rounded hover:bg-green-800/30 text-green-400 transition-colors disabled:opacity-40"
                title="Install to PATH"
              >
                <Download size={14} />
              </button>
            )}
          </div>
        ) : (
          <span className="text-[var(--muted)]">—</span>
        )}
      </td>
    </tr>
  )
}
