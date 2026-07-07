import { Link } from "react-router-dom"
import { ArrowUpRight, ArrowDownLeft } from "lucide-react"
import { useGraph } from "@/services/api/hooks"
import { KindBadge } from "@/components/KindBadge"
import { detailPath } from "@/lib/labels"

/** One end of a `requires` edge, resolved to a navigable deployment. */
interface Related {
  name: string
  kind: string | null // null → not a local node (e.g. a remote reference)
  bind: string | null
}

// Kinds with a local detail page. A `reference` (external service on another node)
// has none, so it's shown inert rather than linking to a route that 404s.
const NAVIGABLE = new Set(["service", "static", "tool", "job"])

/**
 * The dependency edges of a deployment, both directions, as links. "Depends on" =
 * outgoing `requires` edges (this → target); "Required by" = incoming (peer → this).
 * Only deployment-kind edges are navigable — system (package) requirements aren't
 * entities. Renders nothing when the node sits on no edges. Data: GET /graph.
 */
export function RelatedDeployments({ name }: { name: string }) {
  const { data: graph } = useGraph()
  if (!graph) return null

  const nodeKind = (n: string) => graph.nodes.find((x) => x.name === n)?.kind ?? null
  const edges = graph.edges.filter((e) => e.kind === "deployment")

  const dependsOn: Related[] = edges
    .filter((e) => e.src === name)
    .map((e) => ({ name: e.dst, kind: nodeKind(e.dst), bind: e.bind }))
  const requiredBy: Related[] = edges
    .filter((e) => e.dst === name)
    .map((e) => ({ name: e.src, kind: nodeKind(e.src), bind: e.bind }))

  if (dependsOn.length === 0 && requiredBy.length === 0) return null

  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
      <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider mb-1">
        Dependencies
      </h2>
      <p className="text-xs text-[var(--muted)] mb-4">
        How this deployment connects to others (declared <span className="font-mono">requires</span>).
      </p>
      <div className="space-y-4">
        {dependsOn.length > 0 && (
          <RelatedGroup
            icon={<ArrowUpRight size={12} className="shrink-0" />}
            label="Depends on"
            items={dependsOn}
          />
        )}
        {requiredBy.length > 0 && (
          <RelatedGroup
            icon={<ArrowDownLeft size={12} className="shrink-0" />}
            label="Required by"
            items={requiredBy}
          />
        )}
      </div>
    </div>
  )
}

function RelatedGroup({
  icon,
  label,
  items,
}: {
  icon: React.ReactNode
  label: string
  items: Related[]
}) {
  return (
    <div>
      <span className="flex items-center gap-1 text-xs text-[var(--muted)] mb-1">
        {icon}
        {label}
      </span>
      <div className="space-y-1">
        {items.map((r) => (
          <RelatedRow key={`${label}:${r.name}`} related={r} />
        ))}
      </div>
    </div>
  )
}

function RelatedRow({ related }: { related: Related }) {
  const inner = (
    <>
      <span className="font-mono">{related.name}</span>
      {related.kind && <KindBadge kind={related.kind} />}
      {related.bind && (
        <span className="text-xs text-[var(--muted)] font-mono">· {related.bind}</span>
      )}
    </>
  )
  // A local deployment resolves to a detail page; a reference or bare ref (no
  // detail route) is shown inert — there's nothing on this node to navigate to.
  if (!related.kind || !NAVIGABLE.has(related.kind)) {
    return <div className="flex items-center gap-2 text-sm px-2 py-1.5 -mx-2">{inner}</div>
  }
  return (
    <Link
      to={detailPath(related.name, related.kind)}
      className="flex items-center gap-2 rounded px-2 py-1.5 -mx-2 text-sm hover:bg-black/20 transition-colors"
    >
      {inner}
    </Link>
  )
}
