import { GitBranch, Loader2, RefreshCw } from "lucide-react"
import type { GitStatus } from "@/types"

interface GitSyncRowProps {
  status: GitStatus
  program: string // the program whose page this is (excluded from "shared by")
  loading: boolean // a fetch/refresh of the status is in flight
  syncing: boolean // a git pull is in flight
  onSync: () => void
}

// The "Git" value cell in the Program Info card: branch · behind/ahead · dirty,
// plus a Sync (git pull) button. Pull-only — converge stays a separate step. For a
// monorepo, sync operates on the whole repo and lists the sibling programs.
export function GitSyncRow({ status, program, loading, syncing, onSync }: GitSyncRowProps) {
  const behind = status.behind ?? 0
  const ahead = status.ahead ?? 0

  return (
    <span className="flex items-center gap-2 flex-wrap">
      <span className="flex items-center gap-1.5">
        <GitBranch size={13} className="text-[var(--muted)]" />
        <span className="font-mono">{status.detached ? "detached" : status.branch ?? "—"}</span>
      </span>

      {status.behind === null ? (
        <span className="text-xs text-[var(--muted)]">no upstream</span>
      ) : behind > 0 ? (
        <span className="text-xs text-amber-400">
          ● {behind} behind{ahead > 0 ? `, ${ahead} ahead` : ""}
        </span>
      ) : (
        <span className="text-xs text-[var(--muted)]">
          ✓ up to date{ahead > 0 ? ` (${ahead} ahead)` : ""}
        </span>
      )}

      <span className={`text-xs ${status.dirty ? "text-amber-400" : "text-[var(--muted)]"}`}>
        · {status.dirty ? "dirty" : "clean"}
      </span>

      {status.error && (
        <span className="text-xs text-red-400" title={status.error}>
          · fetch error
        </span>
      )}

      {status.repo?.multi && (
        <span
          className="text-xs text-[var(--muted)]"
          title={`Shared repo — syncing pulls the whole ${status.repo.key} working copy`}
        >
          · shared by {status.repo.programs.filter((p) => p !== program).join(", ")}
        </span>
      )}

      <button
        onClick={onSync}
        disabled={syncing || loading}
        title={
          status.repo?.multi
            ? `git pull the whole ${status.repo.key} repo (${status.repo.programs.join(", ")})`
            : status.dirty
              ? "Working copy has local changes — a pull may be refused"
              : "git pull (fast-forward)"
        }
        className="flex items-center gap-1 px-2 py-0.5 text-xs rounded border border-[var(--border)] text-[var(--foreground)] hover:bg-[var(--muted)]/10 transition-colors disabled:opacity-40"
      >
        {syncing ? (
          <Loader2 size={12} className="animate-spin" />
        ) : (
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
        )}
        {status.repo?.multi ? "Sync repo" : "Sync"}
      </button>
    </span>
  )
}
