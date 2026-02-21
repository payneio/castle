import { useState } from "react"
import { Link } from "react-router-dom"
import { ArrowLeft, Check, Loader2, Zap } from "lucide-react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { apiClient } from "@/services/api/client"
import type { ComponentDetail } from "@/types"
import { AddComponent } from "@/components/AddComponent"
import { ComponentEditor } from "@/components/ComponentEditor"

interface ApplyResult {
  ok: boolean
  actions: string[]
  errors: string[]
}

export function ConfigEditorPage() {
  const qc = useQueryClient()
  const [applying, setApplying] = useState(false)
  const [message, setMessage] = useState<{ type: "ok" | "error"; text: string } | null>(null)
  const [applyResult, setApplyResult] = useState<ApplyResult | null>(null)

  const { data: components, isLoading, refetch } = useQuery({
    queryKey: ["config-components"],
    queryFn: async () => {
      const list = await apiClient.get<{ id: string }[]>("/components")
      const details = await Promise.all(
        list.map((c) => apiClient.get<ComponentDetail>(`/components/${c.id}`))
      )
      return details
    },
  })

  const handleSave = async (name: string, config: Record<string, unknown>) => {
    setMessage(null)
    setApplyResult(null)
    try {
      await apiClient.put(`/config/components/${name}`, { config })
      setMessage({ type: "ok", text: `Saved ${name}` })
      refetch()
      qc.invalidateQueries({ queryKey: ["components"] })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setMessage({ type: "error", text: msg })
    }
  }

  const handleDelete = async (name: string) => {
    setMessage(null)
    try {
      await apiClient.delete(`/config/components/${name}`)
      setMessage({ type: "ok", text: `Removed ${name}` })
      refetch()
      qc.invalidateQueries({ queryKey: ["components"] })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setMessage({ type: "error", text: msg })
    }
  }

  const handleApply = async () => {
    setApplying(true)
    setMessage(null)
    setApplyResult(null)
    try {
      const result = await apiClient.post<ApplyResult>("/config/apply")
      setApplyResult(result)
      setMessage({
        type: result.ok ? "ok" : "error",
        text: result.ok ? "Applied successfully" : "Applied with errors",
      })
      qc.invalidateQueries({ queryKey: ["components"] })
      qc.invalidateQueries({ queryKey: ["status"] })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setMessage({ type: "error", text: msg })
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <Link to="/" className="text-[var(--primary)] hover:underline flex items-center gap-1">
            <ArrowLeft size={16} /> Dashboard
          </Link>
          <h1 className="text-2xl font-bold">Configuration</h1>
        </div>
        <button
          onClick={handleApply}
          disabled={applying}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded bg-blue-700 hover:bg-blue-600 text-white transition-colors disabled:opacity-40"
        >
          {applying ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
          Apply All
        </button>
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

      {applyResult && (
        <div className="mb-4 bg-[var(--card)] border border-[var(--border)] rounded-lg p-4 text-sm space-y-1">
          {applyResult.actions.map((a, i) => (
            <div key={i} className="text-green-400">{a}</div>
          ))}
          {applyResult.errors.map((e, i) => (
            <div key={i} className="text-red-400">{e}</div>
          ))}
        </div>
      )}

      {isLoading ? (
        <p className="text-[var(--muted)]">Loading components...</p>
      ) : (
        <div className="space-y-2">
          {components?.map((comp) => (
            <ComponentEditor
              key={comp.id}
              component={comp}
              onSave={handleSave}
              onDelete={handleDelete}
            />
          ))}
          <AddComponent
            existingNames={components?.map((c) => c.id) ?? []}
            onAdd={handleSave}
          />
        </div>
      )}
    </div>
  )
}
