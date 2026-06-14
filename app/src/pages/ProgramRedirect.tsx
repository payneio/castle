import { useParams, Navigate } from "react-router-dom"
import { useDeployment } from "@/services/api/hooks"

export function ProgramRedirect() {
  const { name } = useParams<{ name: string }>()
  const { data: deployment, isLoading, error } = useDeployment(name ?? "")

  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8 text-[var(--muted)]">Loading...</div>
    )
  }

  if (error || !deployment) {
    return <Navigate to={`/programs/${name}`} replace />
  }

  if (deployment.managed && !deployment.schedule) {
    return <Navigate to={`/services/${name}`} replace />
  }

  if (deployment.managed && deployment.schedule) {
    return <Navigate to={`/jobs/${name}`} replace />
  }

  return <Navigate to={`/programs/${name}`} replace />
}
