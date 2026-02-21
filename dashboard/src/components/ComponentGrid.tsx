import type { ComponentSummary, HealthStatus } from "@/types"
import { ComponentCard } from "./ComponentCard"

const ROLE_ORDER = ["service", "tool", "worker", "job", "frontend", "remote", "containerized"]
const ROLE_LABELS: Record<string, string> = {
  service: "Services",
  tool: "Tools",
  worker: "Workers",
  job: "Jobs",
  frontend: "Frontends",
  remote: "Remote",
  containerized: "Containers",
}

interface ComponentGridProps {
  components: ComponentSummary[]
  statuses: HealthStatus[]
}

export function ComponentGrid({ components, statuses }: ComponentGridProps) {
  const statusMap = new Map(statuses.map((s) => [s.id, s]))

  // Group by primary role
  const groups = new Map<string, ComponentSummary[]>()
  for (const comp of components) {
    const primary = comp.roles[0] ?? "tool"
    const list = groups.get(primary) ?? []
    list.push(comp)
    groups.set(primary, list)
  }

  return (
    <div className="space-y-8">
      {ROLE_ORDER.map((role) => {
        const items = groups.get(role)
        if (!items?.length) return null
        return (
          <section key={role}>
            <h2 className="text-lg font-semibold mb-3 text-[var(--muted)]">
              {ROLE_LABELS[role] ?? role}
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
