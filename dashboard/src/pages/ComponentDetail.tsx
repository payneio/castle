import { useState } from "react"
import { useParams, Link, useNavigate } from "react-router-dom"
import { ArrowLeft, Check, Play, RefreshCw, Square } from "lucide-react"
import { useQueryClient } from "@tanstack/react-query"
import { apiClient } from "@/services/api/client"
import { useComponent, useStatus, useServiceAction, useEventStream } from "@/services/api/hooks"
import { ComponentFields } from "@/components/ComponentFields"
import { HealthBadge } from "@/components/HealthBadge"
import { LogViewer } from "@/components/LogViewer"
import { RoleBadge } from "@/components/RoleBadge"

export function ComponentDetailPage() {
  useEventStream()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { name } = useParams<{ name: string }>()
  const { data: component, isLoading, error, refetch } = useComponent(name ?? "")
  const { data: statusResp } = useStatus()
  const { mutate, isPending } = useServiceAction()
  const health = statusResp?.statuses.find((s) => s.id === name)
  const isDown = health?.status === "down"
  const [message, setMessage] = useState<{ type: "ok" | "error"; text: string } | null>(null)

  const handleSave = async (compName: string, config: Record<string, unknown>) => {
    setMessage(null)
    try {
      await apiClient.put(`/config/components/${compName}`, { config })
      setMessage({ type: "ok", text: "Saved to castle.yaml" })
      refetch()
      qc.invalidateQueries({ queryKey: ["components"] })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setMessage({ type: "error", text: msg })
    }
  }

  const handleDelete = async (compName: string) => {
    try {
      await apiClient.delete(`/config/components/${compName}`)
      qc.invalidateQueries({ queryKey: ["components"] })
      navigate("/")
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setMessage({ type: "error", text: msg })
    }
  }

  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8 text-[var(--muted)]">
        Loading...
      </div>
    )
  }

  if (error || !component) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8">
        <Link to="/" className="text-[var(--primary)] hover:underline flex items-center gap-1 mb-4">
          <ArrowLeft size={16} /> Back
        </Link>
        <p className="text-red-400">Component not found</p>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <Link to="/" className="text-[var(--primary)] hover:underline flex items-center gap-1 mb-6">
        <ArrowLeft size={16} /> Back
      </Link>

      <div className="flex items-start justify-between mb-4">
        <h1 className="text-2xl font-bold">{component.id}</h1>
        <div className="flex items-center gap-2">
          {health && <HealthBadge status={health.status} latency={health.latency_ms} />}
          {component.managed && (
            <div className="flex items-center gap-1 ml-2">
              {isDown && (
                <button
                  onClick={() => mutate({ name: component.id, action: "start" })}
                  disabled={isPending}
                  className="p-1.5 rounded hover:bg-green-800/30 text-green-400 transition-colors disabled:opacity-40"
                  title="Start"
                >
                  <Play size={16} />
                </button>
              )}
              <button
                onClick={() => mutate({ name: component.id, action: "restart" })}
                disabled={isPending}
                className="p-1.5 rounded hover:bg-blue-800/30 text-blue-400 transition-colors disabled:opacity-40"
                title="Restart"
              >
                <RefreshCw size={16} />
              </button>
              {!isDown && (
                <button
                  onClick={() => mutate({ name: component.id, action: "stop" })}
                  disabled={isPending}
                  className="p-1.5 rounded hover:bg-red-800/30 text-red-400 transition-colors disabled:opacity-40"
                  title="Stop"
                >
                  <Square size={16} />
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="flex gap-1.5 mb-6">
        {component.roles.map((role) => (
          <RoleBadge key={role} role={role} />
        ))}
      </div>

      {message && (
        <div
          className={`mb-4 px-3 py-2 rounded text-sm ${
            message.type === "ok"
              ? "bg-green-900/30 text-green-300 border border-green-800"
              : "bg-red-900/30 text-red-300 border border-red-800"
          }`}
        >
          <span className="flex items-center gap-1.5">
            {message.type === "ok" && <Check size={14} />}
            {message.text}
          </span>
        </div>
      )}

      <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
        <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider mb-4">
          Configuration
        </h2>
        <ComponentFields
          component={component}
          onSave={handleSave}
          onDelete={handleDelete}
        />
      </div>

      {component.managed && (
        <div className="mb-6">
          <h2 className="text-lg font-semibold mb-3">Logs</h2>
          <LogViewer name={component.id} />
        </div>
      )}
    </div>
  )
}
