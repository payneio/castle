import type { ComponentSummary, HealthStatus } from "@/types"
import { BEHAVIOR_LABELS } from "@/lib/labels"
import { ComponentCard } from "./ComponentCard"

const BEHAVIOR_ORDER = ["daemon", "tool", "frontend"]

interface ComponentGridProps {
  components: ComponentSummary[]
  statuses: HealthStatus[]
}

export function ComponentGrid({ components, statuses }: ComponentGridProps) {
  const statusMap = new Map(statuses.map((s) => [s.id, s]))

  // Group by behavior
  const groups = new Map<string, ComponentSummary[]>()
  for (const comp of components) {
    const key = comp.behavior ?? "other"
    const list = groups.get(key) ?? []
    list.push(comp)
    groups.set(key, list)
  }

  return (
    <div className="space-y-8">
      {BEHAVIOR_ORDER.map((key) => {
        const items = groups.get(key)
        if (!items?.length) return null
        return (
          <section key={key}>
            <h2 className="text-lg font-semibold mb-3 text-[var(--muted)]">
              {BEHAVIOR_LABELS[key] ?? key}
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {items.map((comp) => (
                <ComponentCard
                  key={comp.id}
                  component={comp}
                  health={statusMap.get(comp.id)}
                />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}
