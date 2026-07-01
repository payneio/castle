import { Link } from "react-router-dom"
import type { ProgramSummary } from "@/types"
import { BehaviorBadge } from "./BehaviorBadge"
import { StackBadge } from "./StackBadge"
import { ProgramActions } from "./ProgramActions"

interface ProgramCardProps {
  program: ProgramSummary
}

export function ProgramCard({ program }: ProgramCardProps) {
  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5">
      <div className="flex items-start justify-between mb-2">
        <Link
          to={`/programs/${program.id}`}
          className="text-base font-semibold hover:text-[var(--primary)] transition-colors"
        >
          {program.id}
        </Link>
      </div>

      <div className="flex flex-wrap gap-1.5 mb-2">
        <BehaviorBadge behavior={program.behavior} />
        <StackBadge stack={program.stack} />
      </div>

      {program.description && (
        <p className="text-sm text-[var(--muted)] mb-3">{program.description}</p>
      )}

      <ProgramActions
        name={program.id}
        actions={program.actions}
        active={program.active}
        behavior={program.behavior}
        deployedAs={[...program.services, ...program.jobs]}
        compact
      />
    </div>
  )
}
