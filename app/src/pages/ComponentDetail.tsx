import { useParams } from "react-router-dom"
import { useProgram, useEventStream, useToolDetail } from "@/services/api/hooks"
import { runnerLabel } from "@/lib/labels"
import { DetailHeader } from "@/components/detail/DetailHeader"
import { ConfigPanel } from "@/components/detail/ConfigPanel"
import { ProgramActions } from "@/components/ProgramActions"

export function ComponentDetailPage() {
  useEventStream()
  const { name } = useParams<{ name: string }>()
  const { data: component, isLoading, error, refetch } = useProgram(name ?? "")
  const isTool = component?.behavior === "tool"
  const { data: toolDetail } = useToolDetail(isTool ? (name ?? "") : "")

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
        <ProgramActions name={component.id} actions={component.actions} installed={component.installed} />
      </DetailHeader>

      {component.description && (
        <p className="text-sm text-[var(--muted)] -mt-4 mb-6">{component.description}</p>
      )}

      {toolDetail && (
        <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
          <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider mb-1">
            Tool Info
          </h2>
          <p className="text-xs text-[var(--muted)] mb-4">
            How this tool is packaged and what it depends on.
          </p>
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm mb-4">
            {toolDetail.source && (
              <>
                <span className="text-[var(--muted)]">Source</span>
                <span className="font-mono">{toolDetail.source}</span>
              </>
            )}
            {toolDetail.version && (
              <>
                <span className="text-[var(--muted)]">Version</span>
                <span>{toolDetail.version}</span>
              </>
            )}
            {toolDetail.runner && (
              <>
                <span className="text-[var(--muted)]">Runner</span>
                <span>{runnerLabel(toolDetail.runner)}</span>
              </>
            )}
            <span className="text-[var(--muted)]">Installed</span>
            <span>{component.installed ? "Yes" : "No"}</span>
          </div>
          {toolDetail.system_dependencies.length > 0 && (
            <div className="mb-4">
              <span className="text-sm text-[var(--muted)] block mb-1">System Dependencies</span>
              <div className="flex flex-wrap gap-1">
                {toolDetail.system_dependencies.map((dep) => (
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
          {toolDetail.docs && (
            <div>
              <span className="text-sm text-[var(--muted)] block mb-1">Documentation</span>
              <pre className="text-sm whitespace-pre-wrap bg-[var(--background)] rounded p-3 border border-[var(--border)]">
                {toolDetail.docs}
              </pre>
            </div>
          )}
        </div>
      )}

      <ConfigPanel component={component} configSection="programs" onRefetch={refetch} />
    </div>
  )
}
