import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { ExternalLink, Map as MapIcon, Maximize2, Search } from "lucide-react"
import { useGateway, useGraph, useMeshDeployments } from "@/services/api/hooks"

// The command palette — the keyboard twin of the map's inspect panel. ⌘K from
// anywhere: an empty query is the "Start Menu" (launchable apps); typing searches
// every deployment. Enter launches (or, for non-launchable, jumps to it on the map).
interface AppItem {
  id: string
  name: string
  kind: string
  machine: string | null // remote hostname, or null for local
  launchUrl?: string
  detailPath: string
  mapNodeId: string
}

function detailPathFor(kind: string, name: string): string {
  if (kind === "job") return `/jobs/${name}`
  if (kind === "tool") return `/tools/${name}`
  if (kind === "reference") return `/map`
  return `/services/${name}`
}

// Parent: owns only the open state + the global ⌘K / event triggers. The body
// mounts fresh each open (so query/selection reset for free).
export function CommandPalette() {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setOpen((o) => !o)
      }
    }
    const onOpen = () => setOpen(true)
    window.addEventListener("keydown", onKey)
    window.addEventListener("open-command-palette", onOpen)
    return () => {
      window.removeEventListener("keydown", onKey)
      window.removeEventListener("open-command-palette", onOpen)
    }
  }, [])
  if (!open) return null
  return <PaletteBody onClose={() => setOpen(false)} />
}

function PaletteBody({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const { data: graph } = useGraph()
  const { data: gateway } = useGateway()
  const { data: mesh } = useMeshDeployments()
  const [query, setQuery] = useState("")
  const [sel, setSel] = useState(0)

  const apps = useMemo<AppItem[]>(() => {
    const domain = gateway?.domain
    const out: AppItem[] = []
    for (const n of graph?.nodes ?? []) {
      const launchUrl =
        n.kind === "reference"
          ? (n.base_url ?? undefined)
          : domain &&
              n.reach &&
              n.reach !== "off" &&
              (n.kind === "static" || (n.kind === "service" && n.endpoints.some((e) => e.protocol === "http")))
            ? `https://${n.name}.${domain}`
            : undefined
      out.push({
        id: n.name,
        name: n.name,
        kind: n.kind,
        machine: null,
        launchUrl,
        detailPath: detailPathFor(n.kind, n.name),
        mapNodeId: n.name,
      })
    }
    for (const md of mesh?.deployments ?? []) {
      // A remote app is launchable at <subdomain>.<node-domain> when the node has an
      // acme domain and the app is http-exposed (subdomain set); references carry base_url.
      const remoteLaunch =
        md.kind === "reference"
          ? (md.base_url ?? undefined)
          : md.subdomain && md.domain
            ? `https://${md.subdomain}.${md.domain}`
            : undefined
      out.push({
        id: `${md.node}/${md.name}`,
        name: md.name,
        kind: md.kind,
        machine: md.node,
        launchUrl: remoteLaunch,
        detailPath: `/node/${md.node}`,
        mapNodeId: `__remote_${md.node}_${md.name}__`,
      })
    }
    return out
  }, [graph, gateway, mesh])

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    // Empty query = the Start Menu: just the launchable apps, browsable.
    if (!q) return apps.filter((a) => a.launchUrl)
    return apps.filter((a) => a.name.toLowerCase().includes(q) || a.kind.includes(q))
  }, [apps, query])

  const launch = (a: AppItem) => {
    onClose()
    if (a.launchUrl) window.open(a.launchUrl, "_blank", "noreferrer")
    else navigate(`/map?focus=${encodeURIComponent(a.mapNodeId)}`)
  }
  const goToMap = (a: AppItem) => {
    onClose()
    navigate(`/map?focus=${encodeURIComponent(a.mapNodeId)}`)
  }
  const details = (a: AppItem) => {
    onClose()
    navigate(a.detailPath)
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center bg-black/50 pt-[12vh]" onClick={onClose}>
      <div
        className="w-full max-w-lg overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-[var(--border)] px-3">
          <Search size={15} className="shrink-0 text-[var(--muted)]" />
          <input
            autoFocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setSel(0)
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault()
                setSel((s) => Math.min(s + 1, results.length - 1))
              } else if (e.key === "ArrowUp") {
                e.preventDefault()
                setSel((s) => Math.max(s - 1, 0))
              } else if (e.key === "Enter") {
                e.preventDefault()
                const r = results[sel]
                if (r) launch(r)
              } else if (e.key === "Escape") {
                onClose()
              }
            }}
            placeholder="Launch or find anything…"
            className="flex-1 bg-transparent py-3 text-sm text-[var(--foreground)] outline-none placeholder:text-[var(--muted)]"
          />
          <kbd className="shrink-0 rounded bg-black/40 px-1 text-[10px] text-[var(--muted)]">esc</kbd>
        </div>
        <div className="max-h-[50vh] overflow-y-auto py-1">
          {results.length === 0 && (
            <div className="px-3 py-6 text-center text-xs text-[var(--muted)]">No matches.</div>
          )}
          {results.map((a, i) => (
            <div
              key={a.id}
              onMouseEnter={() => setSel(i)}
              onClick={() => launch(a)}
              className={`flex cursor-pointer items-center gap-2 px-3 py-2 text-sm ${i === sel ? "bg-white/10" : ""}`}
            >
              <span className="min-w-0 flex-1 truncate text-[var(--card-foreground)]">{a.name}</span>
              {a.machine && (
                <span className="shrink-0 rounded bg-[#e879f9]/20 px-1 text-[9px] text-[#e879f9]">{a.machine}</span>
              )}
              <span className="shrink-0 rounded bg-black/30 px-1.5 text-[9px] uppercase text-[var(--muted)]">
                {a.kind}
              </span>
              {a.launchUrl && (
                <button
                  onClick={(e) => (e.stopPropagation(), launch(a))}
                  title="Launch in a new tab"
                  className="shrink-0 text-[var(--muted)] hover:text-[var(--primary)]"
                >
                  <ExternalLink size={13} />
                </button>
              )}
              <button
                onClick={(e) => (e.stopPropagation(), goToMap(a))}
                title="Go to on map"
                className="shrink-0 text-[var(--muted)] hover:text-[var(--card-foreground)]"
              >
                <MapIcon size={13} />
              </button>
              <button
                onClick={(e) => (e.stopPropagation(), details(a))}
                title="Castle details"
                className="shrink-0 text-[var(--muted)] hover:text-[var(--card-foreground)]"
              >
                <Maximize2 size={12} />
              </button>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-between border-t border-[var(--border)] px-3 py-1.5 text-[10px] text-[var(--muted)]">
          <span>↑↓ navigate · ↵ launch/open · esc close</span>
          <span>
            {results.length} {query ? "matches" : "apps"}
          </span>
        </div>
      </div>
    </div>
  )
}
