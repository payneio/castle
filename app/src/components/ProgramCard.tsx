import { Link } from "react-router-dom"
import type { ProgramSummary } from "@/types"
import { KindBadge } from "./KindBadge"
import { StackBadge } from "./StackBadge"

interface ProgramCardProps {
  program: ProgramSummary
}

export function ProgramCard({ program }: ProgramCardProps) {
  // The dot reflects the uniform lifecycle state (a tool on PATH, a service
  // running, a static site served). Lifecycle controls live on the detail page's
  // Deployment section, not here — a card just shows state and links through.
  const dot =
    program.active === true
      ? "bg-green-500"
      : program.active === false
        ? "bg-[var(--muted)]"
        : "bg-transparent border border-[var(--muted)]"

  return (
    <div className="relative bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 hover:border-[var(--primary)] transition-colors">
      <div className="flex items-center gap-2 mb-2">
        <span
          className={`h-2 w-2 rounded-full shrink-0 ${dot}`}
          title={program.active === true ? "active" : program.active === false ? "inactive" : "no deployment"}
        />
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
        <p className="text-sm text-[var(--muted)]">{program.description}</p>
      )}
    </div>
  )
}
