import { cn } from "@/lib/utils"
import { ROLE_DESCRIPTIONS } from "@/lib/labels"

const roleColors: Record<string, string> = {
  service: "bg-green-700 text-white",
  tool: "bg-blue-700 text-white",
  worker: "bg-blue-500 text-white",
  job: "bg-purple-700 text-white",
  frontend: "bg-yellow-600 text-black",
  remote: "bg-gray-600 text-gray-200",
  containerized: "bg-orange-600 text-black",
}

export function RoleBadge({ role }: { role: string }) {
  return (
    <span
      className={cn(
        "inline-block text-[0.65rem] font-semibold uppercase px-1.5 py-0.5 rounded",
        roleColors[role] ?? "bg-gray-600 text-gray-200",
      )}
      title={ROLE_DESCRIPTIONS[role]}
    >
      {role}
    </span>
  )
}
