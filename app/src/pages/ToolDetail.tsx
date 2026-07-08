import { useParams, Link } from "react-router-dom"
import { Loader2 } from "lucide-react"
import { useApply, useDeployment, useSetEnabled } from "@/services/api/hooks"
import { kindIcon } from "@/lib/labels"
import { DetailHeader } from "@/components/detail/DetailHeader"
import { ConfigPanel } from "@/components/detail/ConfigPanel"
import { RelatedDeployments } from "@/components/detail/RelatedDeployments"

const ProgramIcon = kindIcon("program")

export function ToolDetailPage() {
  const { name } = useParams<{ name: string }>()
  const { data: deployment, isLoading, error, refetch } = useDeployment(name ?? "")

  if (isLoading) {
    return <div className="max-w-3xl mx-auto px-6 py-8 text-[var(--muted)]">Loading...</div>
  }

  if (error || !deployment) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8">
        <DetailHeader backTo="/tools" backLabel="Back to Tools" name={name ?? ""} />
        <p className="text-red-400">Tool not found</p>
      </div>
    )
  }

  const program = (deployment.manifest?.program as string | undefined) ?? deployment.id

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <DetailHeader
        backTo="/tools"
        backLabel="Back to Tools"
        name={deployment.id}
        kind="tool"
        stack={deployment.stack}
        source={deployment.source}
      />

      {deployment.description && (
        <p className="text-sm text-[var(--muted)] -mt-4 mb-6">{deployment.description}</p>
      )}

      {/* A tool's PATH deployment: enabling converges it onto PATH, disabling
          removes it. `installed` is the live state; `enabled` the desired one. */}
      <PathLifecycle
        name={deployment.id}
        enabled={deployment.enabled}
        installed={deployment.installed}
        onDone={refetch}
      />

      <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
        <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">
          Program
        </h2>
        <p className="text-sm text-[var(--muted)] mb-2">
          This tool is installed from a program — its source, dev verbs, and catalog
          config live there.
        </p>
        <Link
          to={`/programs/${program}`}
          className="inline-flex items-center gap-1.5 text-sm text-[var(--primary)] hover:underline"
        >
          <ProgramIcon size={14} /> {program}
        </Link>
      </div>

      <RelatedDeployments name={deployment.id} />

      <ConfigPanel deployment={deployment} configSection="tools" onRefetch={refetch} />
    </div>
  )
}

/** Enable/disable a tool — convergence installs it onto PATH or removes it. */
function PathLifecycle({
  name,
  enabled,
  installed: installedState,
  onDone,
}: {
  name: string
  enabled: boolean
  installed: boolean | null
  onDone: () => void
}) {
  const setEnabled = useSetEnabled()
  const apply = useApply()
  const installed = installedState === true
  // Drift: the desired state (enabled) and the actual state (installed) disagree —
  // config says it should be on PATH but isn't, or vice versa. The enable/disable
  // toggle changes *intent*; converging is a separate act, so offer an Apply button
  // that reconciles reality to the current intent without flipping it.
  const drift = installedState !== null && installedState !== enabled
  const busy = setEnabled.isPending || apply.isPending
  const dot =
    installedState === true
      ? "bg-green-500"
      : installedState === false
        ? "bg-[var(--muted)]"
        : "bg-transparent border border-[var(--muted)]"
  return (
    <div className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--card)] px-4 py-3 mb-6">
      <div className="flex items-center gap-2 text-sm">
        <span className={`h-2 w-2 rounded-full shrink-0 ${dot}`} />
        <span>{installed ? "Installed on PATH" : "Not installed"}</span>
        {!enabled && <span className="text-xs text-amber-400">disabled</span>}
        {drift && <span className="text-xs text-amber-400">needs apply</span>}
        <span className="text-xs text-[var(--muted)]">manager: path</span>
      </div>
      <div className="flex items-center gap-2">
        {drift && (
          <button
            onClick={() => apply.mutate({ name }, { onSuccess: onDone })}
            disabled={busy}
            title={enabled ? "Converge onto PATH" : "Remove from PATH"}
            className="flex items-center gap-1.5 px-2.5 py-1 text-sm rounded border border-green-800 text-green-400 hover:bg-green-800/30 transition-colors disabled:opacity-40"
          >
            {apply.isPending && <Loader2 size={14} className="animate-spin" />}
            {enabled ? "Install" : "Uninstall"}
          </button>
        )}
        <button
          onClick={() => setEnabled.mutate({ name, enabled: !enabled }, { onSuccess: onDone })}
          disabled={busy}
          className={`flex items-center gap-1.5 px-2.5 py-1 text-sm rounded border transition-colors disabled:opacity-40 ${
            enabled
              ? "border-red-800 text-red-400 hover:bg-red-800/30"
              : "border-green-800 text-green-400 hover:bg-green-800/30"
          }`}
        >
          {setEnabled.isPending && <Loader2 size={14} className="animate-spin" />}
          {enabled ? "Disable" : "Enable"}
        </button>
      </div>
    </div>
  )
}
