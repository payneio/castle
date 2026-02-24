import { Play, RefreshCw, Square } from "lucide-react"
import { useServiceAction } from "@/services/api/hooks"
import type { HealthStatus } from "@/types"

interface ServiceControlsProps {
  name: string
  health?: HealthStatus
}

export function ServiceControls({ name, health }: ServiceControlsProps) {
  const { mutate, isPending } = useServiceAction()
  const isDown = health?.status === "down"

  return (
    <div className="flex items-center gap-1">
      {isDown && (
        <button
          onClick={() => mutate({ name, action: "start" })}
          disabled={isPending}
          className="p-1.5 rounded hover:bg-green-800/30 text-green-400 transition-colors disabled:opacity-40"
          title="Start"
        >
          <Play size={16} />
        </button>
      )}
      <button
        onClick={() => mutate({ name, action: "restart" })}
        disabled={isPending}
        className="p-1.5 rounded hover:bg-blue-800/30 text-blue-400 transition-colors disabled:opacity-40"
        title="Restart"
      >
        <RefreshCw size={16} />
      </button>
      {!isDown && (
        <button
          onClick={() => mutate({ name, action: "stop" })}
          disabled={isPending}
          className="p-1.5 rounded hover:bg-red-800/30 text-red-400 transition-colors disabled:opacity-40"
          title="Stop"
        >
          <Square size={16} />
        </button>
      )}
    </div>
  )
}
