import { useState } from "react"
import { Link } from "react-router-dom"
import { Server, Clock, Plus, Loader2, ExternalLink } from "lucide-react"
import type { ProgramDetail } from "@/types"
import { useServices, useJobs, useProgramAction } from "@/services/api/hooks"
import { subdomainUrl } from "@/lib/labels"
import { CreateDeploymentForm, type CreatePrefill } from "./CreateDeploymentForm"

/** How a program is deployed, and its lifecycle. A program → 0-N deployments.
 * Its own path (tool) / caddy (static) deployment is 1:1 with the program, so its
 * lifecycle is shown inline here; service/job deployments link to their own pages
 * where start/stop lives. This is the single home for "how this program runs". */
export function DeploymentsSection({ program }: { program: ProgramDetail }) {
  const { deployments } = program
  const [creating, setCreating] = useState(false)

  const { data: allServices } = useServices()
  const { data: allJobs } = useJobs()
  const existing = [
    ...(allServices ?? []).map((s) => s.id),
    ...(allJobs ?? []).map((j) => j.id),
  ]

  const prefill: CreatePrefill = {
    name: program.id,
    program: program.id,
    runTarget: program.id,
    launcher: program.stack?.startsWith("python") || !program.stack ? "python" : "command",
  }

  // Tool/static deployments are 1:1 with the program (same name) — their
  // lifecycle is shown inline; service/job deployments link to their own pages.
  const inline = deployments.filter((d) => d.kind === "tool" || d.kind === "static")
  const linked = deployments.filter((d) => d.kind === "service" || d.kind === "job")

  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider">
          Deployment
        </h2>
        <button
          onClick={() => setCreating((c) => !c)}
          className="flex items-center gap-1 text-xs text-[var(--primary)] hover:underline"
        >
          <Plus size={12} /> Add deployment
        </button>
      </div>
      <p className="text-xs text-[var(--muted)] mb-4">
        How this program is materialized into the runtime.
      </p>

      {/* The program's own path/caddy deployment — its lifecycle, inline. */}
      {inline.map((d) =>
        d.kind === "tool" ? (
          <PathLifecycle key={d.name} name={program.id} active={program.active} />
        ) : (
          <StaticStatus key={d.name} name={program.id} active={program.active} />
        ),
      )}

      {creating && (
        <CreateDeploymentForm
          prefill={prefill}
          existingNames={existing}
          onCancel={() => setCreating(false)}
        />
      )}

      {/* Service/job deployments — managed on their own detail pages. */}
      {deployments.length === 0 && !creating ? (
        <p className="text-sm text-[var(--muted)]">No deployment yet.</p>
      ) : linked.length > 0 ? (
        <div className="space-y-1.5 mt-1">
          {linked.map((d) => (
            <Link
              key={d.name}
              to={d.kind === "job" ? `/jobs/${d.name}` : `/services/${d.name}`}
              className="flex items-center gap-2 text-sm hover:text-[var(--primary)] transition-colors"
            >
              {d.kind === "job" ? (
                <Clock size={14} className="text-[var(--muted)]" />
              ) : (
                <Server size={14} className="text-[var(--muted)]" />
              )}
              <span className="font-medium">{d.name}</span>
              <span className="text-xs text-[var(--muted)]">{d.kind}</span>
            </Link>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function Dot({ active }: { active: boolean | null }) {
  const cls =
    active === true
      ? "bg-green-500"
      : active === false
        ? "bg-[var(--muted)]"
        : "bg-transparent border border-[var(--muted)]"
  return <span className={`h-2 w-2 rounded-full shrink-0 ${cls}`} />
}

/** A tool's PATH deployment: install/uninstall is its start/stop (manager=path). */
function PathLifecycle({ name, active }: { name: string; active: boolean | null }) {
  const { mutate, isPending } = useProgramAction()
  const installed = active === true
  return (
    <div className="flex items-center justify-between rounded border border-[var(--border)] px-3 py-2 mb-3">
      <div className="flex items-center gap-2 text-sm">
        <Dot active={active} />
        <span>{installed ? "Installed on PATH" : "Not installed"}</span>
        <span className="text-xs text-[var(--muted)]">manager: path</span>
      </div>
      <button
        onClick={() => mutate({ name, action: installed ? "uninstall" : "install" })}
        disabled={isPending}
        className={`flex items-center gap-1.5 px-2 py-1 text-sm rounded border transition-colors disabled:opacity-40 ${
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

/** A static (caddy) deployment: served by the gateway from its built dir. */
function StaticStatus({ name, active }: { name: string; active: boolean | null }) {
  const url = subdomainUrl(name)
  const served = active === true
  return (
    <div className="flex items-center justify-between rounded border border-[var(--border)] px-3 py-2 mb-3">
      <div className="flex items-center gap-2 text-sm">
        <Dot active={active} />
        <span>{served ? "Served by the gateway" : "Not built yet"}</span>
        <span className="text-xs text-[var(--muted)]">manager: caddy</span>
      </div>
      {url && served && (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-sm text-[var(--primary)] hover:underline"
        >
          {name}
          <ExternalLink size={11} className="opacity-60" />
        </a>
      )}
    </div>
  )
}
