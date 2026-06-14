import { useState } from "react"
import { useParams } from "react-router-dom"
import { useProgram, useEventStream } from "@/services/api/hooks"
import { runnerLabel } from "@/lib/labels"
import { DetailHeader } from "@/components/detail/DetailHeader"
import { ConfigPanel } from "@/components/detail/ConfigPanel"
import { ProgramActions, ActionOutputPanel, type ActionOutput } from "@/components/ProgramActions"

export function ProgramDetailPage() {
  useEventStream()
  const { name } = useParams<{ name: string }>()
  const { data: component, isLoading, error, refetch } = useProgram(name ?? "")
  const [actionOutput, setActionOutput] = useState<ActionOutput | null>(null)

  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8 text-[var(--muted)]">Loading...</div>
    )
  }

  if (error || !component) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8">
        <DetailHeader backTo="/" backLabel="Back" name={name ?? ""} />
        <p className="text-red-400">Program not found</p>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <DetailHeader
        backTo="/"
        backLabel="Back to Programs"
        name={component.id}
        behavior={component.behavior}
        stack={component.stack}
        source={component.source}
      >
        <ProgramActions name={component.id} actions={component.actions} installed={component.installed} onOutput={setActionOutput} />
      </DetailHeader>

      {actionOutput && actionOutput.action && (
        <div className="-mt-2 mb-6">
          <ActionOutputPanel output={actionOutput} onDismiss={() => setActionOutput(null)} />
        </div>
      )}

      {component.description && (
        <p className="text-sm text-[var(--muted)] -mt-4 mb-6">{component.description}</p>
      )}

      <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
        <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider mb-1">
          Program Info
        </h2>
        <p className="text-xs text-[var(--muted)] mb-4">
          Where the source lives and how castle works with it.
        </p>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm mb-4">
          {component.source && (
            <>
              <span className="text-[var(--muted)]">Source</span>
              <span className="font-mono break-all">{component.source}</span>
            </>
          )}
          {component.repo && (
            <>
              <span className="text-[var(--muted)]">Repo</span>
              <span className="font-mono break-all">
                {component.repo}
                {component.ref ? ` @ ${component.ref}` : ""}
              </span>
            </>
          )}
          {component.version && (
            <>
              <span className="text-[var(--muted)]">Version</span>
              <span>{component.version}</span>
            </>
          )}
          {component.runner && (
            <>
              <span className="text-[var(--muted)]">Runner</span>
              <span>{runnerLabel(component.runner)}</span>
            </>
          )}
          {component.installed !== null && (
            <>
              <span className="text-[var(--muted)]">Installed</span>
              <span>{component.installed ? "Yes" : "No"}</span>
            </>
          )}
        </div>

        {component.commands && Object.keys(component.commands).length > 0 && (
          <div className="mb-4">
            <span className="text-sm text-[var(--muted)] block mb-1">Commands</span>
            <div className="space-y-1">
              {Object.entries(component.commands).map(([verb, cmds]) => (
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

        {component.system_dependencies.length > 0 && (
          <div className="mb-4">
            <span className="text-sm text-[var(--muted)] block mb-1">System Dependencies</span>
            <div className="flex flex-wrap gap-1">
              {component.system_dependencies.map((dep) => (
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

      <ConfigPanel component={component} configSection="programs" onRefetch={refetch} />
    </div>
  )
}
