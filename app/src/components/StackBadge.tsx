import { stackLabel } from "@/lib/labels"

export function StackBadge({ stack }: { stack: string | null }) {
  if (!stack) return null

  return (
    <span className="text-[0.65rem] font-mono px-1.5 py-0.5 rounded bg-[var(--border)] text-[var(--muted)]">
      {stackLabel(stack)}
    </span>
  )
}
