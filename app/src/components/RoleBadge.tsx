import { cn } from "@/lib/utils"
import { CATEGORY_DESCRIPTIONS } from "@/lib/labels"

const categoryColors: Record<string, string> = {
  service: "bg-green-700 text-white",
  job: "bg-purple-700 text-white",
  tool: "bg-blue-700 text-white",
  frontend: "bg-yellow-600 text-black",
  component: "bg-gray-600 text-gray-200",
}

export function RoleBadge({ role }: { role: string }) {
  return (
    <span
      className={cn(
        "inline-block text-[0.65rem] font-semibold uppercase px-1.5 py-0.5 rounded",
        categoryColors[role] ?? "bg-gray-600 text-gray-200",
      )}
      title={CATEGORY_DESCRIPTIONS[role]}
    >
      {role}
    </span>
  )
}
