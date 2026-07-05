import { useState } from "react"
import { GitFork, Loader2, RefreshCw } from "lucide-react"
import { useRepos, useRepoSync } from "@/services/api/hooks"
import type { RepoSummary } from "@/types"

// Repos that back more than one program (monorepos) get one row with a single
// repo-scoped Sync — the honest place for it, since a pull moves the whole working
// copy. Standalone programs (a repo of one) sync from their own program page.
export function MonorepoBanner() {
  const { data: repos } = useRepos()
  const monorepos = (repos ?? []).filter((r) => r.programs.length > 1)
  if (monorepos.length === 0) return null
  return (
    <div className="mb-4 space-y-2">
      {monorepos.map((r) => (
        <MonorepoRow key={r.key} repo={r} />
      ))}
    </div>
  )
}

function MonorepoRow({ repo }: { repo: RepoSummary }) {
  const sync = useRepoSync()
  const [msg, setMsg] = useState<string | null>(null)

  const behind = repo.behind ?? 0
  const onSync = () => {
    setMsg(null)
    sync.mutate(repo.key, {
      onSuccess: (d) =>
        setMsg(d.pulled ? `Pulled — ${d.deployments.join(", ")} may need restart/apply` : "Already up to date"),
      onError: (e) => {
        let t = String(e)
        try {
          t = JSON.parse((e as Error).message).detail ?? t
        } catch {
          t = (e as Error).message ?? t
        }
        setMsg(t)
      },
    })
  }

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-4 py-2.5">
      <div className="flex items-center gap-2 text-sm flex-wrap">
        <GitFork size={15} className="text-[var(--muted)]" />
        <span className="font-mono font-semibold">{repo.key}</span>
        <span className="text-xs text-[var(--muted)]">monorepo · {repo.programs.join(", ")}</span>
        {behind > 0 ? (
          <span className="text-xs text-amber-400">● {behind} behind</span>
        ) : (
          <span className="text-xs text-[var(--muted)]">✓ up to date</span>
        )}
        {repo.dirty && <span className="text-xs text-amber-400">· dirty</span>}
        <button
          onClick={onSync}
          disabled={sync.isPending}
          className="ml-auto flex items-center gap-1 px-2 py-0.5 text-xs rounded border border-[var(--border)] hover:bg-[var(--muted)]/10 transition-colors disabled:opacity-40"
        >
          {sync.isPending ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          Sync repo
        </button>
      </div>
      {msg && <div className="text-xs text-[var(--muted)] mt-1.5">{msg}</div>}
    </div>
  )
}
