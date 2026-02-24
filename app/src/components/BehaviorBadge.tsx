import { cn } from "@/lib/utils"
import { BEHAVIOR_DESCRIPTIONS, behaviorLabel } from "@/lib/labels"

const behaviorColors: Record<string, string> = {
  daemon: "bg-green-700 text-white",
  tool: "bg-blue-700 text-white",
  frontend: "bg-yellow-600 text-black",
}

export function BehaviorBadge({ behavior }: { behavior: string | null }) {
  if (!behavior) return null

  return (
    <span
      className={cn(
        "inline-block text-[0.65rem] font-semibold uppercase px-1.5 py-0.5 rounded",
        behaviorColors[behavior] ?? "bg-gray-600 text-gray-200",
      )}
      title={BEHAVIOR_DESCRIPTIONS[behavior]}
    >
      {behaviorLabel(behavior)}
    </span>
  )
}
