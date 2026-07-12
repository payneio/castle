import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, Check, GitCompare, Loader2, Play } from "lucide-react"
import { apiClient } from "@/services/api/client"
import type { ApplyResult } from "@/services/api/hooks"

// A terraform-style "plan then apply" for the whole node: preview the diff the
// converge would enact (activate/restart/deactivate), then apply it.
export function ConvergePanel() {
  const qc = useQueryClient()
  const [plan, setPlan] = useState<ApplyResult | null>(null)
  const [busy, setBusy] = useState<"plan" | "apply" | null>(null)
  const [msg, setMsg] = useState<string | null>(null)

  const preview = async () => {
    setBusy("plan")
    setMsg(null)
    try {
      setPlan(await apiClient.post<ApplyResult>("/apply", { plan: true }))
    } finally {
      setBusy(null)
    }
  }

  const apply = async () => {
    setBusy("apply")
    setMsg(null)
    try {
      await apiClient.post<ApplyResult>("/apply", {})
      setPlan(null)
      setMsg("Applied — the node is converged.")
      qc.invalidateQueries()
    } catch (e) {
      // A self-apply restarts castle-api, dropping the connection — expected.
      if (e instanceof TypeError) {
        setPlan(null)
        setMsg("Applied — services are restarting.")
      } else {
        setMsg(`Apply failed: ${e instanceof Error ? e.message : String(e)}`)
      }
    } finally {
      setBusy(null)
    }
  }

  const row = (label: string, names: string[], color: string) =>
    names.length > 0 && (
      <div className="flex gap-2 text-sm">
        <span className={`w-24 shrink-0 ${color}`}>{label}</span>
        <span className="font-mono text-[var(--muted)]">{names.join(", ")}</span>
      </div>
    )

  return (
    <div className="mt-6 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-[var(--muted)]">
          <GitCompare size={16} />
          <span>Convergence</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={preview}
            disabled={busy !== null}
            className="flex items-center gap-1.5 px-2.5 py-1 text-sm rounded border border-[var(--border)] hover:border-[var(--primary)] transition-colors disabled:opacity-40"
          >
            {busy === "plan" ? <Loader2 size={14} className="animate-spin" /> : <GitCompare size={14} />}
            Preview
          </button>
          {plan?.changed && (
            <button
              onClick={apply}
              disabled={busy !== null}
              className="flex items-center gap-1.5 px-2.5 py-1 text-sm rounded bg-[var(--primary)] text-white hover:opacity-90 transition-opacity disabled:opacity-40"
            >
              {busy === "apply" ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              Apply
            </button>
          )}
        </div>
      </div>

      {msg && (
        <div className="mt-3 flex items-center gap-1.5 text-sm text-green-400">
          <Check size={14} /> {msg}
        </div>
      )}

      {/* Advisory warnings from the render/preflight (missing stack toolchains,
          acme prerequisites, tunnel notes) — surfaced so a service that can't
          build or start doesn't fail silently at apply time. */}
      {plan?.messages
        ?.filter((m) => m.startsWith("Warning"))
        .map((m) => (
          <div key={m} className="mt-2 flex items-start gap-1.5 text-sm text-amber-400">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            <span>{m.replace(/^Warning:\s*/, "")}</span>
          </div>
        ))}

      {plan && (
        <div className="mt-3 space-y-1">
          {plan.changed ? (
            <>
              {row("activate", plan.activated, "text-green-400")}
              {row("restart", plan.restarted, "text-blue-400")}
              {row("deactivate", plan.deactivated, "text-red-400")}
            </>
          ) : (
            <div className="text-sm text-[var(--muted)]">In sync — nothing to converge.</div>
          )}
        </div>
      )}
    </div>
  )
}
