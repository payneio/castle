import { cn } from "@/lib/utils"
import { KIND_DESCRIPTIONS, kindIcon, kindLabel } from "@/lib/labels"

// Derived deployment kind → badge color.
const kindColors: Record<string, string> = {
  service: "bg-green-700 text-white",
  job: "bg-purple-700 text-white",
  tool: "bg-blue-700 text-white",
  static: "bg-cyan-700 text-white",
  reference: "bg-gray-600 text-gray-200",
}

export function KindBadge({ kind }: { kind: string | null }) {
  if (!kind) return null
  const Icon = kindIcon(kind)

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-[0.65rem] font-semibold uppercase px-1.5 py-0.5 rounded",
        kindColors[kind] ?? "bg-gray-600 text-gray-200",
      )}
      title={KIND_DESCRIPTIONS[kind]}
    >
      <Icon size={11} className="shrink-0" />
      {kindLabel(kind)}
    </span>
  )
}
