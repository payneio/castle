import { useParams, Link } from "react-router-dom"
import { Loader2, Package } from "lucide-react"
import { useDeployment, useProgramAction } from "@/services/api/hooks"
import { DetailHeader } from "@/components/detail/DetailHeader"
import { ConfigPanel } from "@/components/detail/ConfigPanel"

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

      {/* A tool's PATH deployment: install/uninstall is its start/stop. */}
      <PathLifecycle name={deployment.id} active={deployment.active} onDone={refetch} />

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
          <Package size={14} /> {program}
        </Link>
      </div>

      <ConfigPanel deployment={deployment} configSection="tools" onRefetch={refetch} />
    </div>
  )
}

/** Install/uninstall a tool on PATH — the path deployment's lifecycle. */
function PathLifecycle({
  name,
  active,
  onDone,
}: {
  name: string
  active: boolean | null
  onDone: () => void
}) {
  const { mutate, isPending } = useProgramAction()
  const installed = active === true
  const dot =
    active === true
      ? "bg-green-500"
      : active === false
        ? "bg-[var(--muted)]"
        : "bg-transparent border border-[var(--muted)]"
  return (
    <div className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--card)] px-4 py-3 mb-6">
      <div className="flex items-center gap-2 text-sm">
        <span className={`h-2 w-2 rounded-full shrink-0 ${dot}`} />
        <span>{installed ? "Installed on PATH" : "Not installed"}</span>
        <span className="text-xs text-[var(--muted)]">manager: path</span>
      </div>
      <button
        onClick={() =>
          mutate({ name, action: installed ? "uninstall" : "install" }, { onSuccess: onDone })
        }
        disabled={isPending}
        className={`flex items-center gap-1.5 px-2.5 py-1 text-sm rounded border transition-colors disabled:opacity-40 ${
          installed
            ? "border-red-800 text-red-400 hover:bg-red-800/30"
            : "border-green-800 text-green-400 hover:bg-green-800/30"
        }`}
      >
        {isPending && <Loader2 size={14} className="animate-spin" />}
        {installed ? "Uninstall" : "Install"}
      </button>
    </div>
  )
}
