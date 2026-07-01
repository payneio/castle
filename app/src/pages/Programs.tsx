import { usePrograms } from "@/services/api/hooks"
import { ProgramList } from "@/components/ProgramList"
import { PageHeader } from "@/components/PageHeader"

export function Programs() {
  const { data: programs, isLoading } = usePrograms()

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <PageHeader title="Programs" subtitle="Software catalog" />

      {isLoading ? (
        <p className="text-[var(--muted)]">Loading...</p>
      ) : programs && programs.length > 0 ? (
        <ProgramList programs={programs} filterable />
      ) : (
        <p className="text-[var(--muted)]">No programs yet.</p>
      )}
    </div>
  )
}
