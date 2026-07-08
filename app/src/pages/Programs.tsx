import { useState } from "react"
import { Plus } from "lucide-react"
import { usePrograms } from "@/services/api/hooks"
import { ProgramList } from "@/components/ProgramList"
import { MonorepoBanner } from "@/components/MonorepoBanner"
import { PageHeader } from "@/components/PageHeader"
import { AddProgramForm } from "@/components/AddProgramForm"

export function Programs() {
  const { data: programs, isLoading } = usePrograms()
  const [adding, setAdding] = useState(false)

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <PageHeader
        title="Programs"
        subtitle="Software catalog"
        actions={
          <button
            onClick={() => setAdding((a) => !a)}
            className="flex items-center gap-1 px-3 py-1.5 text-sm rounded border border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--primary)] transition-colors"
          >
            <Plus size={14} /> Add program
          </button>
        }
      />

      <MonorepoBanner />

      {adding && (
        <div className="mb-6 max-w-2xl">
          <AddProgramForm
            existingNames={(programs ?? []).map((p) => p.id)}
            onCancel={() => setAdding(false)}
          />
        </div>
      )}

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
