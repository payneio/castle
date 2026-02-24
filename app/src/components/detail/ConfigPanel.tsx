import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { Check } from "lucide-react"
import { apiClient } from "@/services/api/client"
import type { AnyDetail } from "@/types"
import { ComponentFields } from "@/components/ComponentFields"

interface ConfigPanelProps {
  component: AnyDetail
  configSection: "services" | "jobs" | "programs"
  onRefetch: () => void
}

export function ConfigPanel({ component, configSection, onRefetch }: ConfigPanelProps) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [message, setMessage] = useState<{ type: "ok" | "error"; text: string } | null>(null)

  const handleSave = async (compName: string, config: Record<string, unknown>) => {
    setMessage(null)
    try {
      await apiClient.put(`/config/${configSection}/${compName}`, { config })
      setMessage({ type: "ok", text: "Saved to castle.yaml" })
      onRefetch()
      qc.invalidateQueries({ queryKey: [configSection] })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setMessage({ type: "error", text: msg })
    }
  }

  const handleDelete = async (compName: string) => {
    try {
      await apiClient.delete(`/config/${configSection}/${compName}`)
      qc.invalidateQueries({ queryKey: [configSection] })
      navigate("/")
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setMessage({ type: "error", text: msg })
    }
  }

  return (
    <>
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
    </>
  )
}
