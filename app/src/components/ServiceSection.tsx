import { useMemo, useState } from "react"
import type { ServiceSummary, HealthStatus } from "@/types"
import { ServiceCard } from "./ServiceCard"
import { kindLabel } from "@/lib/labels"
import { cn } from "@/lib/utils"

interface ServiceSectionProps {
  services: ServiceSummary[]
  statuses: HealthStatus[]
}

// The services page mixes systemd services and caddy statics — both URL-reachable.
const KIND_ORDER = ["service", "static"]

// Active chip color per kind — mirrors KindBadge so the filter reads as the badge.
const KIND_ACTIVE: Record<string, string> = {
  service: "bg-green-700 text-white border-green-600",
  static: "bg-cyan-700 text-white border-cyan-600",
}

export function ServiceSection({ services, statuses }: ServiceSectionProps) {
  const statusMap = useMemo(() => new Map(statuses.map((s) => [s.id, s])), [statuses])
  const [search, setSearch] = useState("")
  const [kind, setKind] = useState<string | null>(null)

  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const s of services) {
      const k = s.kind ?? "service"
      c[k] = (c[k] ?? 0) + 1
    }
    return c
  }, [services])
  const kindsPresent = KIND_ORDER.filter((k) => counts[k])

  // Sort by name so statics and systemd services interleave alphabetically rather
  // than clumping by kind (the registry lists them per-kind store).
  const filtered = useMemo(() => {
    let base = [...services].sort((a, b) => a.id.localeCompare(b.id))
    if (kind) base = base.filter((s) => (s.kind ?? "service") === kind)
    if (search) {
      const q = search.toLowerCase()
      base = base.filter(
        (s) =>
          s.id.toLowerCase().includes(q) ||
          (s.description?.toLowerCase().includes(q) ?? false),
      )
    }
    return base
  }, [services, search, kind])

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter services..."
          className="bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--primary)] w-56"
        />
        {kindsPresent.length > 1 && (
          <div className="flex flex-wrap gap-1.5">
            <Chip
              label={`All (${services.length})`}
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
        <p className="text-[var(--muted)]">No services match.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((svc) => (
            <ServiceCard key={svc.id} service={svc} health={statusMap.get(svc.id)} />
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
