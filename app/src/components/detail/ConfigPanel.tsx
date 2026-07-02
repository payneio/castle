import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { Check, RefreshCw } from "lucide-react"
import { apiClient } from "@/services/api/client"
import type {
  AnyDetail,
  DeploymentDetail,
  ProgramDetail,
  ServiceDetail,
  JobDetail,
} from "@/types"
import { ProgramFields } from "./ProgramFields"
import { ServiceFields } from "./ServiceFields"
import { JobFields } from "./JobFields"
import { ToolFields } from "./ToolFields"
import { StaticFields } from "./StaticFields"

interface ConfigPanelProps {
  deployment: AnyDetail | DeploymentDetail
  configSection: "services" | "jobs" | "programs" | "tools" | "static"
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
  // Programs are their own catalog; every deployment kind (service/job/tool/
  // static) lives in the single deployments/ collection.
  const writeSection = isDeployment ? "deployments" : "programs"

  const handleSave = async (compName: string, config: Record<string, unknown>) => {
    setMessage(null)
    try {
      await apiClient.put(`/config/${writeSection}/${compName}`, { config })
      setMessage({
        type: "ok",
        text: isDeployment
          ? "Saved to castle.yaml — not live yet; apply to converge."
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
      // One converge: renders units/routes and reconciles the runtime (restarts
      // only what changed). No separate restart call needed.
      await apiClient.post(`/apply`, { name: deployment.id })
      setPendingApply(false)
      setMessage({ type: "ok", text: "Applied — the change is now live." })
      qc.invalidateQueries()
      onRefetch()
    } catch (e: unknown) {
      // A self-apply of castle-api restarts it, killing the connection — expected.
      if (e instanceof TypeError) {
        setPendingApply(false)
        setMessage({ type: "ok", text: "Applied — the service is restarting." })
        setApplying(false)
        return
      }
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
    // Deleting a program cascades: its deployments are torn down and removed too
    // (a program and its 1:1 tool/static deployment are one thing). Deleting a
    // service/job deployment is a plain removal (keeps the program).
    const url =
      configSection === "programs"
        ? `/config/programs/${compName}?cascade=true`
        : `/config/${writeSection}/${compName}`
    try {
      await apiClient.delete(url)
      qc.invalidateQueries({ queryKey: [configSection] })
      qc.invalidateQueries({ queryKey: ["programs"] })
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
              {applying ? "Applying…" : "Apply"}
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
        ) : configSection === "tools" ? (
          <ToolFields
            tool={deployment as DeploymentDetail}
            onSave={handleSave}
            onDelete={handleDelete}
          />
        ) : configSection === "static" ? (
          <StaticFields
            static_={deployment as DeploymentDetail}
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
