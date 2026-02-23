import { Link } from "react-router-dom"
import { Network, Wifi, WifiOff } from "lucide-react"
import { cn } from "@/lib/utils"
import type { MeshStatus } from "@/types"

interface MeshPanelProps {
  mesh: MeshStatus
}

export function MeshPanel({ mesh }: MeshPanelProps) {
  if (!mesh.enabled) return null

  return (
    <section className="border border-[var(--border)] rounded-lg overflow-hidden bg-[var(--card)]">
      <div className="flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          <Network size={16} className="text-[var(--primary)]" />
          <h2 className="font-semibold text-sm">Mesh</h2>
          <span
            className={cn(
              "inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full",
              mesh.mqtt_connected
                ? "bg-green-800/50 text-green-300"
                : "bg-red-800/50 text-red-300",
            )}
          >
            {mesh.mqtt_connected ? (
              <Wifi size={10} />
            ) : (
              <WifiOff size={10} />
            )}
            {mesh.mqtt_connected ? "connected" : "disconnected"}
          </span>
        </div>

        <div className="flex items-center gap-4 text-xs text-[var(--muted)]">
          {mesh.mqtt_broker_host && (
            <span className="font-mono">
              mqtt://{mesh.mqtt_broker_host}:{mesh.mqtt_broker_port}
            </span>
          )}
          {mesh.mdns_enabled && (
            <span>mDNS active</span>
          )}
          <span>
            {mesh.peer_count} peer{mesh.peer_count !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      {mesh.peers.length > 0 && (
        <div className="border-t border-[var(--border)] px-4 py-2 flex items-center gap-2">
          <span className="text-xs text-[var(--muted)]">Peers:</span>
          {mesh.peers.map((peer) => (
            <Link
              key={peer}
              to={`/node/${peer}`}
              className="text-xs font-mono px-2 py-0.5 rounded bg-[var(--border)] hover:text-[var(--foreground)] transition-colors"
            >
              {peer}
            </Link>
          ))}
        </div>
      )}
    </section>
  )
}
