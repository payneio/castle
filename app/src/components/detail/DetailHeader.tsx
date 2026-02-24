import { Link } from "react-router-dom"
import { ArrowLeft } from "lucide-react"
import { BehaviorBadge } from "@/components/BehaviorBadge"
import { StackBadge } from "@/components/StackBadge"

interface DetailHeaderProps {
  backTo: string
  backLabel: string
  name: string
  behavior?: string | null
  stack?: string | null
  source?: string | null
  children?: React.ReactNode
}

export function DetailHeader({ backTo, backLabel, name, behavior, stack, source, children }: DetailHeaderProps) {
  return (
    <>
      <Link to={backTo} className="text-[var(--primary)] hover:underline flex items-center gap-1 mb-6">
        <ArrowLeft size={16} /> {backLabel}
      </Link>

      <div className="flex items-start justify-between mb-4">
        <h1 className="text-2xl font-bold">{name}</h1>
        {children}
      </div>

      <div className="flex items-center gap-3 mb-6">
        <BehaviorBadge behavior={behavior ?? null} />
        <StackBadge stack={stack ?? null} />
        {source && (
          <span className="text-sm text-[var(--muted)] font-mono">{source}</span>
        )}
      </div>
    </>
  )
}
