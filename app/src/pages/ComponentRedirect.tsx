import { useParams, Navigate } from "react-router-dom"
import { useComponent } from "@/services/api/hooks"

export function ComponentRedirect() {
  const { name } = useParams<{ name: string }>()
  const { data: component, isLoading, error } = useComponent(name ?? "")

  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8 text-[var(--muted)]">Loading...</div>
    )
  }

  if (error || !component) {
    return <Navigate to={`/components/${name}`} replace />
  }

  if (component.managed && !component.schedule) {
    return <Navigate to={`/services/${name}`} replace />
  }

  if (component.managed && component.schedule) {
    return <Navigate to={`/scheduled/${name}`} replace />
  }

  return <Navigate to={`/components/${name}`} replace />
}
