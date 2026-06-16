import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { Check, RefreshCw } from "lucide-react"
import { apiClient } from "@/services/api/client"
import type { AnyDetail, ProgramDetail, ServiceDetail, JobDetail } from "@/types"
import { ProgramFields } from "./ProgramFields"
import { ServiceFields } from "./ServiceFields"
import { JobFields } from "./JobFields"

interface ConfigPanelProps {
  deployment: AnyDetail
  configSection: "services" | "jobs" | "programs"
  onRefetch: () => void
}

export function ConfigPanel({ deployment, configSection, onRefetch }: ConfigPanelProps) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [message, setMessage] = useState<{ type: "ok" | "error"; text: string } | null>(null)
  // A deployment edit only persists to castle.yaml; the unit/process still need
  // a deploy (regenerate) + restart to actually take effect.
  const [pendingApply, setPendingApply] = useState(false)
  const [applying, setApplying] = useState(false)
  const isDeployment = configSection !== "programs"

  const handleSave = async (compName: string, config: Record<string, unknown>) => {
    setMessage(null)
    try {
      await apiClient.put(`/config/${configSection}/${compName}`, { config })
      setMessage({
        type: "ok",
        text: isDeployment
          ? "Saved to castle.yaml — not live yet; apply to deploy & restart."
          : "Saved to castle.yaml",
      })
      if (isDeployment) setPendingApply(true)
      onRefetch()
      qc.invalidateQueries({ queryKey: [configSection] })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setMessage({ type: "error", text: msg })
    }
  }

  const handleApply = async () => {
    setApplying(true)
    setMessage(null)
    try {
      await apiClient.post(`/deploy`, { name: deployment.id })
      if (configSection === "services") {
        await apiClient.post(`/services/${deployment.id}/restart`, {})
      }
      setPendingApply(false)
      setMessage({ type: "ok", text: "Applied — the change is now live." })
      qc.invalidateQueries({ queryKey: ["status"] })
      qc.invalidateQueries({ queryKey: [configSection] })
      onRefetch()
    } catch (e: unknown) {
      let msg = e instanceof Error ? e.message : String(e)
      try {
        msg = JSON.parse((e as Error).message).detail ?? msg
      } catch {
        /* keep msg */
      }
      setMessage({ type: "error", text: `Apply failed: ${msg}` })
    } finally {
      setApplying(false)
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
      {(message || pendingApply) && (
        <div
          className={`mb-4 px-3 py-2 rounded text-sm flex items-center justify-between gap-3 ${
            message?.type === "error"
              ? "bg-red-900/30 text-red-300 border border-red-800"
              : pendingApply
                ? "bg-amber-900/30 text-amber-200 border border-amber-800"
                : "bg-green-900/30 text-green-300 border border-green-800"
          }`}
        >
          <span className="flex items-center gap-1.5">
            {message?.type === "ok" && !pendingApply && <Check size={14} />}
            {message?.text}
          </span>
          {pendingApply && (
            <button
              onClick={handleApply}
              disabled={applying}
              className="shrink-0 flex items-center gap-1.5 px-3 py-1 text-xs rounded bg-amber-700 hover:bg-amber-600 text-white transition-colors disabled:opacity-50"
            >
              <RefreshCw size={12} className={applying ? "animate-spin" : ""} />
              {applying
                ? "Applying…"
                : configSection === "services"
                  ? "Apply (deploy & restart)"
                  : "Apply (deploy)"}
            </button>
          )}
        </div>
      )}
      <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
        <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider mb-4">
          Configuration
        </h2>
        {configSection === "programs" ? (
          <ProgramFields
            program={deployment as ProgramDetail}
            onSave={handleSave}
            onDelete={handleDelete}
          />
        ) : configSection === "services" ? (
          <ServiceFields
            service={deployment as ServiceDetail}
            onSave={handleSave}
            onDelete={handleDelete}
          />
        ) : (
          <JobFields
            job={deployment as JobDetail}
            onSave={handleSave}
            onDelete={handleDelete}
          />
        )}
      </div>
    </>
  )
}
