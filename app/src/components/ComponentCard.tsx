import { ExternalLink, Play, RefreshCw, Server, Square, Terminal } from "lucide-react"
import { Link } from "react-router-dom"
import type { ComponentSummary, HealthStatus } from "@/types"
import { useServiceAction } from "@/services/api/hooks"
import { runnerLabel } from "@/lib/labels"
import { HealthBadge } from "./HealthBadge"
import { BehaviorBadge } from "./BehaviorBadge"
import { StackBadge } from "./StackBadge"

interface ComponentCardProps {
  component: ComponentSummary
  health?: HealthStatus
}

export function ComponentCard({ component, health }: ComponentCardProps) {
  const hasHttp = component.port != null
  const { mutate, isPending } = useServiceAction()

  const doAction = (action: string) => {
    mutate({ name: component.id, action })
  }

  const isDown = health?.status === "down"

  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5">
      <div className="flex items-start justify-between mb-2">
        <Link
          to={`/services/${component.id}`}
          className="text-base font-semibold hover:text-[var(--primary)] transition-colors"
        >
          {component.id}
        </Link>
        {health ? (
          <HealthBadge status={health.status} latency={health.latency_ms} />
        ) : hasHttp ? (
          <HealthBadge status="unknown" />
        ) : null}
      </div>

      <div className="flex gap-1.5 mb-2">
        <BehaviorBadge behavior={component.behavior} />
        <StackBadge stack={component.stack} />
      </div>

      {component.description && (
        <p className="text-sm text-[var(--muted)] mb-3">{component.description}</p>
      )}

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 text-xs text-[var(--muted)]">
          {component.port && (
            <span className="flex items-center gap-1 font-mono">
              <Server size={12} />:{component.port}
            </span>
          )}
          {component.runner && (
            <span className="flex items-center gap-1">
              <Terminal size={12} />
              {runnerLabel(component.runner)}
            </span>
          )}
          {component.proxy_path && (
            <a
              href={component.proxy_path + "/"}
              className="flex items-center gap-1 text-[var(--primary)] hover:underline"
            >
              <ExternalLink size={12} />
              {component.proxy_path}
            </a>
          )}
          {component.port && (
            <a
              href={`http://localhost:${component.port}/docs`}
              className="text-[var(--primary)] hover:underline"
            >
              Docs
            </a>
          )}
        </div>

        {component.managed && (
          <div className="flex items-center gap-1">
            {isDown && (
              <button
                onClick={() => doAction("start")}
                disabled={isPending}
                className="p-1 rounded hover:bg-green-800/30 text-green-400 transition-colors disabled:opacity-40"
                title="Start"
              >
                <Play size={14} />
              </button>
            )}
            <button
              onClick={() => doAction("restart")}
              disabled={isPending}
              className="p-1 rounded hover:bg-blue-800/30 text-blue-400 transition-colors disabled:opacity-40"
              title="Restart"
            >
              <RefreshCw size={14} />
            </button>
            {!isDown && (
              <button
                onClick={() => doAction("stop")}
                disabled={isPending}
                className="p-1 rounded hover:bg-red-800/30 text-red-400 transition-colors disabled:opacity-40"
                title="Stop"
              >
                <Square size={14} />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
