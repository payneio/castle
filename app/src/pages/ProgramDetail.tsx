import { useState } from "react"
import { useParams } from "react-router-dom"
import { useProgram, useEventStream } from "@/services/api/hooks"
import { runnerLabel } from "@/lib/labels"
import { DetailHeader } from "@/components/detail/DetailHeader"
import { ConfigPanel } from "@/components/detail/ConfigPanel"
import { DeploymentsSection } from "@/components/detail/DeploymentsSection"
import { ProgramActions, ActionOutputPanel, type ActionOutput } from "@/components/ProgramActions"

export function ProgramDetailPage() {
  useEventStream()
  const { name } = useParams<{ name: string }>()
  const { data: deployment, isLoading, error, refetch } = useProgram(name ?? "")
  const [actionOutput, setActionOutput] = useState<ActionOutput | null>(null)

  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8 text-[var(--muted)]">Loading...</div>
    )
  }

  if (error || !deployment) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8">
        <DetailHeader backTo="/" backLabel="Back" name={name ?? ""} />
        <p className="text-red-400">Program not found</p>
      </div>
    )
  }

  // A static frontend (frontend behavior, build outputs, no service) is served
  // by the gateway in place — show where.
  const buildOutputs = (deployment.manifest.build as { outputs?: string[] } | undefined)?.outputs
  const servedAt =
    deployment.behavior === "frontend" && deployment.services.length === 0 && buildOutputs?.length
      ? deployment.id === "castle-app"
        ? "/"
        : `/${deployment.id}/`
      : null

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <DetailHeader
        backTo="/"
        backLabel="Back to Programs"
        name={deployment.id}
        behavior={deployment.behavior}
        stack={deployment.stack}
        source={deployment.source}
      >
        <ProgramActions
          name={deployment.id}
          actions={deployment.actions}
          active={deployment.active}
          behavior={deployment.behavior}
          deployedAs={[...deployment.services, ...deployment.jobs]}
          onOutput={setActionOutput}
        />
      </DetailHeader>

      {actionOutput && actionOutput.action && (
        <div className="-mt-2 mb-6">
          <ActionOutputPanel output={actionOutput} onDismiss={() => setActionOutput(null)} />
        </div>
      )}

      {deployment.description && (
        <p className="text-sm text-[var(--muted)] -mt-4 mb-6">{deployment.description}</p>
      )}

      <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
        <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider mb-1">
          Program Info
        </h2>
        <p className="text-xs text-[var(--muted)] mb-4">
          Where the source lives and how castle works with it.
        </p>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm mb-4">
          {deployment.source && (
            <>
              <span className="text-[var(--muted)]">Source</span>
              <span className="font-mono break-all">{deployment.source}</span>
            </>
          )}
          {deployment.repo && (
            <>
              <span className="text-[var(--muted)]">Repo</span>
              <span className="font-mono break-all">
                {deployment.repo}
                {deployment.ref ? ` @ ${deployment.ref}` : ""}
              </span>
            </>
          )}
          {deployment.version && (
            <>
              <span className="text-[var(--muted)]">Version</span>
              <span>{deployment.version}</span>
            </>
          )}
          {deployment.runner && (
            <>
              <span className="text-[var(--muted)]">Runner</span>
              <span>{runnerLabel(deployment.runner)}</span>
            </>
          )}
          {deployment.active !== null && (
            <>
              <span className="text-[var(--muted)]">Active</span>
              <span className={deployment.active ? "text-green-400" : "text-[var(--muted)]"}>
                {deployment.active ? "● active" : "○ inactive"}
              </span>
            </>
          )}
          {servedAt && (
            <>
              <span className="text-[var(--muted)]">Reachable at</span>
              <a href={servedAt} className="font-mono break-all text-[var(--primary)] hover:underline">
                {servedAt} <span className="text-[var(--muted)]">· served (static)</span>
              </a>
            </>
          )}
        </div>

        {deployment.commands && Object.keys(deployment.commands).length > 0 && (
          <div className="mb-4">
            <span className="text-sm text-[var(--muted)] block mb-1">Commands</span>
            <div className="space-y-1">
              {Object.entries(deployment.commands).map(([verb, cmds]) => (
                <div key={verb} className="flex gap-2 text-xs">
                  <span className="text-[var(--muted)] w-20 shrink-0">{verb}</span>
                  <span className="font-mono break-all">
                    {cmds.map((argv) => argv.join(" ")).join(" && ")}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {deployment.system_dependencies.length > 0 && (
          <div className="mb-4">
            <span className="text-sm text-[var(--muted)] block mb-1">System Dependencies</span>
            <div className="flex flex-wrap gap-1">
              {deployment.system_dependencies.map((dep) => (
                <span
                  key={dep}
                  className="text-xs px-2 py-0.5 rounded bg-amber-900/30 text-amber-400 border border-amber-800"
                >
                  {dep}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      <DeploymentsSection program={deployment} />

      <ConfigPanel deployment={deployment} configSection="programs" onRefetch={refetch} />
    </div>
  )
}
