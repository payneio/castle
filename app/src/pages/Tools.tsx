import { usePrograms } from "@/services/api/hooks"
import { ProgramList } from "@/components/ProgramList"
import { PageHeader } from "@/components/PageHeader"

export function Tools() {
  // Tools are program-centric — a tool is a program installed on PATH (its path
  // deployment is 1:1 and trivial), so we list the programs that have one.
  const { data: programs, isLoading } = usePrograms("tool")

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <PageHeader title="Tools" subtitle="CLIs installed on your PATH" />

      {isLoading ? (
        <p className="text-[var(--muted)]">Loading...</p>
      ) : programs && programs.length > 0 ? (
        <ProgramList programs={programs} linkBase="/tools" showDeployments={false} />
      ) : (
        <p className="text-[var(--muted)]">No tools yet.</p>
      )}
    </div>
  )
}
