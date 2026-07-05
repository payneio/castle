import { AlertTriangle, CheckCircle2, GitFork, Layers, Link2, Package } from "lucide-react"
import { useGraph } from "@/services/api/hooks"
import type { GraphNode } from "@/types"

// A read-only diagnostic of how programs/deployments relate — repos (provenance),
// `requires` edges (dependency), and the derived predicates functional?/fresh?.
// Everything is computed server-side from git + config; nothing is stored.
export function GraphPage() {
  const { data, isLoading, error } = useGraph()

  if (isLoading) {
    return <div className="max-w-4xl mx-auto px-6 py-8 text-[var(--muted)]">Loading…</div>
  }
  if (error || !data) {
    return <div className="max-w-4xl mx-auto px-6 py-8 text-red-400">Failed to load graph.</div>
  }

  const monorepos = data.repos.filter((r) => r.programs.length > 1)
  const staleRepos = data.repos.filter((r) => r.fresh === false)
  const depEdges = data.edges.filter((e) => e.kind === "deployment")
  const unhealthy = data.nodes.filter((n) => !n.functional)
  const depended = data.nodes
    .filter((n) => n.depended_on_by > 0)
    .sort((a, b) => b.depended_on_by - a.depended_on_by)

  return (
    <div className="max-w-4xl mx-auto px-6 py-8 space-y-6">
      <div>
        <h1 className="text-xl font-bold flex items-center gap-2">
          <GitFork size={20} /> Relationship Graph
        </h1>
        <p className="text-sm text-[var(--muted)] mt-1">
          Derived, never stored — repos from git, <code>requires</code> edges, and the{" "}
          <code>functional?</code> / <code>fresh?</code> predicates, computed on the fly.
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="Repos" value={data.repos.length} sub={`${monorepos.length} monorepo`} />
        <Stat label="Deployments" value={data.nodes.length} />
        <Stat label="requires edges" value={depEdges.length} />
        <Stat
          label="Unmet"
          value={unhealthy.length}
          tone={unhealthy.length ? "warn" : "ok"}
        />
      </div>

      <Card title="Repos" icon={Layers} note="A monorepo is one working copy shared by several programs.">
        {monorepos.length === 0 && (
          <p className="text-sm text-[var(--muted)]">No monorepos — every program has its own repo.</p>
        )}
        {monorepos.map((r) => (
          <div key={r.key} className="flex items-center gap-2 text-sm py-0.5">
            <Package size={13} className="text-[var(--muted)]" />
            <span className="font-mono">{r.key}</span>
            <FreshBadge fresh={r.fresh} behind={r.behind} dirty={r.dirty} />
            <span className="text-[var(--muted)]">→ {r.programs.join(", ")}</span>
          </div>
        ))}
        {staleRepos.length > 0 && (
          <p className="text-xs text-amber-400 mt-2">
            {staleRepos.length} repo(s) not fresh: {staleRepos.map((r) => r.key).join(", ")}
          </p>
        )}
      </Card>

      <Card title="requires (deployment → deployment)" icon={Link2}
        note="Encoded dependency edges. Env for a bound dep is generated from this — never scraped back.">
        {depEdges.length === 0 ? (
          <p className="text-sm text-[var(--muted)]">
            None declared yet — front-end/back-end deps have no encoded edge.
          </p>
        ) : (
          depEdges.map((e, i) => (
            <div key={i} className="text-sm font-mono py-0.5">
              {e.src} <span className="text-[var(--muted)]">requires</span> {e.dst}
              {e.bind && <span className="text-[var(--muted)]"> → ${e.bind}</span>}
            </div>
          ))
        )}
      </Card>

      <Card title="functional?" icon={unhealthy.length ? AlertTriangle : CheckCircle2}
        note="A deployment is functional when every requirement is satisfied (system installed, deployment exists).">
        {unhealthy.length === 0 ? (
          <p className="text-sm text-green-400 flex items-center gap-1.5">
            <CheckCircle2 size={14} /> All deployments functional.
          </p>
        ) : (
          unhealthy.map((n) => (
            <div key={n.name} className="text-sm py-0.5">
              <span className="text-red-400">✗</span> <span className="font-mono">{n.name}</span>{" "}
              <span className="text-[var(--muted)]">unmet: {n.unmet.join(", ")}</span>
            </div>
          ))
        )}
      </Card>

      {depended.length > 0 && (
        <Card title="Widely depended-on" icon={Link2} note="Fan-in — a property, not a category.">
          {depended.map((n: GraphNode) => (
            <div key={n.name} className="text-sm font-mono py-0.5">
              {n.name} <span className="text-[var(--muted)]">← {n.depended_on_by} dependent(s)</span>
            </div>
          ))}
        </Card>
      )}
    </div>
  )
}

function Stat({ label, value, sub, tone }: { label: string; value: number; sub?: string; tone?: "ok" | "warn" }) {
  const color = tone === "warn" ? "text-amber-400" : tone === "ok" ? "text-green-400" : ""
  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-3">
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      <div className="text-xs text-[var(--muted)]">{label}</div>
      {sub && <div className="text-xs text-[var(--muted)]">{sub}</div>}
    </div>
  )
}

function Card({
  title, icon: Icon, note, children,
}: {
  title: string
  icon: typeof Layers
  note?: string
  children: React.ReactNode
}) {
  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5">
      <h2 className="text-sm font-semibold flex items-center gap-1.5 mb-1">
        <Icon size={15} /> {title}
      </h2>
      {note && <p className="text-xs text-[var(--muted)] mb-3">{note}</p>}
      <div className="space-y-0.5">{children}</div>
    </div>
  )
}

function FreshBadge({ fresh, behind, dirty }: { fresh: boolean | null; behind: number | null; dirty: boolean }) {
  if (fresh === null) return null
  if (fresh) return <span className="text-xs text-green-400">fresh</span>
  const bits = [behind ? `${behind} behind` : null, dirty ? "dirty" : null].filter(Boolean)
  return <span className="text-xs text-amber-400">{bits.join(" · ") || "stale"}</span>
}
