import { Link } from "react-router-dom"
import type { ProgramSummary } from "@/types"
import { KindBadge } from "./KindBadge"
import { StackBadge } from "./StackBadge"

interface ProgramCardProps {
  program: ProgramSummary
  // Where the card links. Defaults to the program page; the Tools page passes
  // "/tools" so a tool card opens its tool detail page (a tool is 1:1 with its
  // program, same name).
  linkBase?: string
  // Whether to list the program's deployments. The Programs catalog shows them;
  // a kind-specific lens (e.g. Tools) is already looking at one deployment, so off.
  showDeployments?: boolean
}

export function ProgramCard({
  program,
  linkBase = "/programs",
  showDeployments = true,
}: ProgramCardProps) {
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
          to={`${linkBase}/${program.id}`}
          className="text-base font-semibold hover:text-[var(--primary)] transition-colors after:absolute after:inset-0"
        >
          {program.id}
        </Link>
        <StackBadge stack={program.stack} />
      </div>

      {/* A program has no kind of its own — show its deployments (name · kind).
          Suppressed on kind-specific lenses (e.g. Tools) which already scope to one. */}
      {showDeployments &&
        (program.deployments.length > 0 ? (
          <div className="flex flex-col gap-1 mb-2">
            {program.deployments.map((d) => (
              <div key={d.name} className="flex items-center gap-1.5 text-xs">
                <span className="font-mono text-[var(--muted)]">{d.name}</span>
                <KindBadge kind={d.kind} />
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-[var(--muted)] italic mb-2">no deployment</p>
        ))}

      {program.description && (
        <p className="text-sm text-[var(--muted)]">{program.description}</p>
      )}
    </div>
  )
}
