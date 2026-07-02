import { Power, RefreshCw } from "lucide-react"
import { useServiceAction, useSetEnabled } from "@/services/api/hooks"

interface ServiceControlsProps {
  name: string
  enabled: boolean
}

// Lifecycle is convergence: the Power toggle sets desired on/off state and applies
// (activate/deactivate); Restart is the one imperative bounce. No raw start/stop.
export function ServiceControls({ name, enabled }: ServiceControlsProps) {
  const restart = useServiceAction()
  const setEnabled = useSetEnabled()
  const busy = restart.isPending || setEnabled.isPending

  return (
    <div className="flex items-center gap-1">
      <button
        onClick={() => setEnabled.mutate({ name, enabled: !enabled })}
        disabled={busy}
        className={`p-1.5 rounded transition-colors disabled:opacity-40 ${
          enabled
            ? "hover:bg-red-800/30 text-red-400"
            : "hover:bg-green-800/30 text-green-400"
        }`}
        title={enabled ? "Disable (stop & keep off)" : "Enable (start)"}
      >
        <Power size={16} />
      </button>
      {enabled && (
        <button
          onClick={() => restart.mutate({ name, action: "restart" })}
          disabled={busy}
          className="p-1.5 rounded hover:bg-blue-800/30 text-blue-400 transition-colors disabled:opacity-40"
          title="Restart"
        >
          <RefreshCw size={16} className={restart.isPending ? "animate-spin" : ""} />
        </button>
      )}
    </div>
  )
}
