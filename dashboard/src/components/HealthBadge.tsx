import { cn } from "@/lib/utils"

interface HealthBadgeProps {
  status: "up" | "down" | "unknown"
  latency?: number | null
}

export function HealthBadge({ status, latency }: HealthBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full",
        status === "up" && "bg-green-800/50 text-green-300",
        status === "down" && "bg-red-800/50 text-red-300",
        status === "unknown" && "bg-gray-700/50 text-gray-400",
      )}
    >
      <span
        className={cn(
          "w-1.5 h-1.5 rounded-full",
          status === "up" && "bg-green-400",
          status === "down" && "bg-red-400",
          status === "unknown" && "bg-gray-500",
        )}
      />
      {status}
      {latency != null && status === "up" && (
        <span className="text-gray-500 ml-0.5">{latency}ms</span>
      )}
    </span>
  )
}
