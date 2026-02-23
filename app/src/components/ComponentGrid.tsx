import type { ComponentSummary, HealthStatus } from "@/types"
import { CATEGORY_LABELS } from "@/lib/labels"
import { ComponentCard } from "./ComponentCard"

const CATEGORY_ORDER = ["service", "job", "tool", "frontend", "component"]

interface ComponentGridProps {
  components: ComponentSummary[]
  statuses: HealthStatus[]
}

export function ComponentGrid({ components, statuses }: ComponentGridProps) {
  const statusMap = new Map(statuses.map((s) => [s.id, s]))

  // Group by category
  const groups = new Map<string, ComponentSummary[]>()
  for (const comp of components) {
    const cat = comp.category
    const list = groups.get(cat) ?? []
    list.push(comp)
    groups.set(cat, list)
  }

  return (
    <div className="space-y-8">
      {CATEGORY_ORDER.map((cat) => {
        const items = groups.get(cat)
        if (!items?.length) return null
        return (
          <section key={cat}>
            <h2 className="text-lg font-semibold mb-3 text-[var(--muted)]">
              {CATEGORY_LABELS[cat] ?? cat}
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
