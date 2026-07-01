import { Link } from "react-router-dom"
import type { ProgramSummary } from "@/types"
import { KindBadge } from "./KindBadge"
import { StackBadge } from "./StackBadge"
import { ProgramActions } from "./ProgramActions"

interface ProgramCardProps {
  program: ProgramSummary
}

export function ProgramCard({ program }: ProgramCardProps) {
  return (
    <div className="relative bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 hover:border-[var(--primary)] transition-colors">
      <div className="flex items-start justify-between mb-2">
        <Link
          to={`/programs/${program.id}`}
          className="text-base font-semibold hover:text-[var(--primary)] transition-colors after:absolute after:inset-0"
        >
          {program.id}
        </Link>
      </div>

      <div className="flex flex-wrap gap-1.5 mb-2">
        <KindBadge kind={program.kind} />
        <StackBadge stack={program.stack} />
      </div>

      {program.description && (
        <p className="text-sm text-[var(--muted)] mb-3">{program.description}</p>
      )}

      <div className="relative z-10">
        <ProgramActions
          name={program.id}
          actions={program.actions}
          active={program.active}
          kind={program.kind}
          compact
        />
      </div>
    </div>
  )
}
