import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  Background,
  ControlButton,
  Controls,
  Handle,
  Position,
  ReactFlow,
  SelectionMode,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { useNavigate, useSearchParams } from "react-router-dom"
import {
  BoxSelect,
  ChevronDown,
  ExternalLink,
  Globe,
  LayoutGrid,
  Loader2,
  Lock,
  Maximize2,
  Minus,
  Package,
  Plus,
  RotateCw,
  Router,
  Trash2,
  X,
} from "lucide-react"
import {
  useDeleteDeployment,
  useGateway,
  useGraph,
  useJobs,
  useMeshDeployments,
  useMutateRequires,
  usePrograms,
  useSaveReference,
  useServiceAction,
  useSetReach,
  useSuggestions,
} from "@/services/api/hooks"
import { ConfirmModal } from "@/components/ConfirmModal"
import type { MeshDeployment } from "@/types"

// A spatial, interactive control surface for the whole box. Lanes read left→right:
// leaf tools/jobs, then the service+static spine where every dependency line lives,
// then the exposure lane (gateway → internet). Manipulating the diagram mutates
// config and converges:
//   • drag a node's edge to Internet  → reach: public   (+ apply)
//   • drag a node's edge to Gateway   → reach: internal (+ apply)
//   • delete a green line             → downgrade to internal
//   • delete a blue line              → reach: off (services)
//   • select a node + Delete          → delete the deployment (with confirm)
//   • right-click / ⋯                 → per-deployment action menu
//   • drag a node                     → rearrange (persisted); "Reset layout" restores the columns

const LANES: Record<string, { x: number; title: string; dim?: boolean; exposable?: boolean }> = {
  tool: { x: 0, title: "Tools", dim: true },
  job: { x: 230, title: "Jobs", dim: true },
  service: { x: 470, title: "Services", exposable: true },
  static: { x: 720, title: "Frontends", exposable: true },
}
const PROG_X = -250 // source-only (undeployed) programs — left of everything
const GATEWAY_X = 990
const INTERNET_X = 1220
const ROW_H = 52
const TOP = 70

const KIND_COLOR: Record<string, string> = {
  service: "#2ea043",
  job: "#8957e5",
  tool: "#388bfd",
  static: "#39c5cf",
}

// Dependency edges are colored by the protocol of the thing being consumed (the
// target's endpoint). "system" = a socket-less dep (a tool/package) or a target
// castle doesn't model an endpoint for.
const PROTO_COLOR: Record<string, string> = {
  http: "#58a6ff",
  pg: "#3b82f6",
  bolt: "#22d3ee",
  mqtt: "#a855f7",
  redis: "#ef4444",
  tcp: "#f59e0b",
  system: "#6e7681",
}
const EXTERNAL_X = 1450 // external resources (references) — beyond Internet

const HANDLE = { opacity: 0, width: 8, height: 8 } as const

// User's manual node arrangement. Positions default to the computed lane layout;
// any node the user drags is remembered here and survives refetches + reloads.
const POS_KEY = "castle-map-positions"
type PosMap = Record<string, { x: number; y: number }>
function loadPositions(): PosMap {
  try {
    return JSON.parse(localStorage.getItem(POS_KEY) || "{}") as PosMap
  } catch {
    return {}
  }
}
function savePositions(p: PosMap): void {
  try {
    localStorage.setItem(POS_KEY, JSON.stringify(p))
  } catch {
    /* storage disabled — arrangement is session-only */
  }
}

// A deployment card, split into two zones: a left "source" grip (the program it's
// realized from — a future click target for the program/info panel) and the main
// deployment body. The right handle is a connection *source* (drag it to an
// exposure target); the others exist only to anchor pre-built edges.
function MapNode({ data }: NodeProps) {
  const d = data as {
    label: string
    kind: string
    sub?: string
    dim?: boolean
    exposable?: boolean
    program?: string | null
    reach?: string | null
    launchUrl?: string
    focusDim?: boolean
    focused?: boolean
    onProgram?: (program: string) => void
  }
  const color = KIND_COLOR[d.kind] ?? "#8b949e"
  const ReachIcon = d.reach === "public" ? Globe : d.reach === "internal" ? Router : null
  return (
    <div
      className="group relative flex items-stretch overflow-hidden rounded-md border bg-[var(--card)] text-xs shadow-sm"
      style={{
        borderColor: color,
        width: 156,
        opacity: d.focusDim ? 0.12 : d.dim ? 0.55 : 1,
        boxShadow: d.focused ? `0 0 0 2px ${color}` : undefined,
      }}
    >
      {d.launchUrl && (
        <a
          href={d.launchUrl}
          target="_blank"
          rel="noreferrer"
          className="absolute right-0.5 top-0.5 z-10 rounded bg-[var(--card)]/80 p-0.5 text-[var(--muted)] opacity-0 hover:text-[var(--primary)] group-hover:opacity-100"
          title={`Launch ${d.launchUrl}`}
          onClick={(e) => e.stopPropagation()}
        >
          <ExternalLink size={12} />
        </a>
      )}
      {d.program ? (
        <button
          type="button"
          className="flex w-6 shrink-0 items-center justify-center border-r transition-[filter] hover:brightness-150"
          style={{ borderColor: color, background: `${color}1f`, color }}
          title={`Open program: ${d.program}`}
          onClick={(e) => {
            e.stopPropagation()
            d.onProgram?.(d.program!)
          }}
        >
          <Package size={11} />
        </button>
      ) : (
        // No program (inline infra) — a same-size, non-interactive cell with a
        // muted dash so the grip column stays visually aligned across all cards.
        <div
          className="flex w-6 shrink-0 items-center justify-center border-r opacity-60"
          style={{ borderColor: color, background: `${color}12`, color: "var(--muted)" }}
          title="no program (no source)"
        >
          <Minus size={11} />
        </div>
      )}
      <div className="min-w-0 flex-1 px-2 py-1.5">
        <div className="flex items-center gap-1">
          <span className="min-w-0 flex-1 truncate font-medium text-[var(--card-foreground)]" title={d.label}>
            {d.label}
          </span>
          {ReachIcon && (
            <ReachIcon
              size={10}
              className="shrink-0"
              style={{ color: d.reach === "public" ? "#2ea043" : "#58a6ff" }}
            />
          )}
        </div>
        {d.sub && <div className="truncate text-[10px] text-[var(--muted)]">{d.sub}</div>}
      </div>
      {/* Right handle: drag OUT to connect — to a hub (expose) or another node
          (declare "requires"). Right target lands incoming dependency lines. */}
      <Handle id="rs" type="source" position={Position.Right} style={{ ...HANDLE, opacity: 0.9, background: color }} />
      <Handle id="rt" type="target" position={Position.Right} style={{ ...HANDLE, opacity: 0 }} />
      <Handle id="lt" type="target" position={Position.Left} isConnectable={false} style={{ ...HANDLE, opacity: 0 }} />
      <Handle id="ls" type="source" position={Position.Left} isConnectable={false} style={{ ...HANDLE, opacity: 0 }} />
    </div>
  )
}

// A source-only program (no deployment yet) — the palette for a future
// drag-onto-a-lane "deploy this" gesture. Rendered dashed to read as "not running."
function ProgramNode({ data }: NodeProps) {
  const d = data as { label: string; placeholder?: boolean }
  if (d.placeholder) {
    return (
      <div className="w-[156px] rounded-md border border-dashed border-[var(--border)] px-2 py-2 text-[10px] leading-snug text-[var(--muted)]">
        No source-only programs. Undeployed programs would appear here to drag onto a lane.
      </div>
    )
  }
  return (
    <div className="flex w-[156px] items-center gap-1.5 rounded-md border border-dashed border-[var(--muted)] bg-[var(--card)] px-2 py-1.5 text-xs text-[var(--muted)]">
      <Package size={12} />
      <span className="min-w-0 flex-1 truncate" title={d.label}>
        {d.label}
      </span>
    </div>
  )
}

// Gateway / Internet — the exposure targets. Target handle only (drop a line here).
function HubNode({ data }: NodeProps) {
  const d = data as { label: string; kind: "gateway" | "internet"; sub?: string | null }
  const Icon = d.kind === "internet" ? Globe : Router
  const color = d.kind === "internet" ? "#2ea043" : "#58a6ff"
  return (
    <div
      className="flex flex-col items-center gap-0.5 rounded-lg border-2 bg-[var(--card)] px-3 py-3 text-xs font-semibold"
      style={{ borderColor: color, width: 130, color }}
    >
      <Icon size={20} />
      {d.label}
      {d.sub && (
        <span className="max-w-[118px] truncate font-mono text-[9px] font-normal text-[var(--muted)]" title={d.sub}>
          {d.sub}
        </span>
      )}
      <Handle id="lt" type="target" position={Position.Left} style={{ ...HANDLE, opacity: 0.9, background: color }} />
      <Handle id="rs" type="source" position={Position.Right} isConnectable={false} style={{ ...HANDLE, opacity: 0 }} />
    </div>
  )
}

function LaneNode({ data }: NodeProps) {
  const d = data as { label: string }
  return (
    <div className="text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">{d.label}</div>
  )
}

// A full-width labeled rule separating the remote machine bands above from this
// node's own deployments below.
function DividerNode({ data }: NodeProps) {
  const d = data as { label: string; width: number }
  return (
    <div className="flex items-center gap-2" style={{ width: d.width }}>
      <span className="whitespace-nowrap text-[11px] font-semibold uppercase tracking-wide text-[var(--card-foreground)]">
        {d.label}
      </span>
      <div className="flex-1 border-t border-dashed border-[var(--border)]" />
    </div>
  )
}

// The host + a coarse protocol from a reference's base_url (for chips/labels).
const SCHEME_PROTO: Record<string, string> = { https: "http", http: "http", postgres: "pg", postgresql: "pg", bolt: "bolt", mqtt: "mqtt", redis: "redis" }
function hostOf(url: string | null): string {
  if (!url) return ""
  try {
    return new URL(url).host || url
  } catch {
    return url
  }
}
function protoOf(url: string | null): string {
  if (!url) return "system"
  try {
    return SCHEME_PROTO[new URL(url).protocol.replace(":", "")] ?? "system"
  } catch {
    return "system"
  }
}

// An external resource — a `reference` (manager: none) castle doesn't run. Sits in
// the External zone as a registry entry + a drop target for consumes edges.
function ExternalNode({ data }: NodeProps) {
  const d = data as { label: string; host: string; focusDim?: boolean; focused?: boolean }
  return (
    <div
      className="flex w-[150px] flex-col gap-0.5 rounded-md border border-dashed px-2 py-1.5 text-xs"
      style={{
        borderColor: "#8b949e",
        background: "var(--card)",
        opacity: d.focusDim ? 0.12 : 1,
        boxShadow: d.focused ? "0 0 0 2px #8b949e" : undefined,
      }}
    >
      <div className="flex items-center gap-1 text-[var(--card-foreground)]">
        <ExternalLink size={11} className="shrink-0 text-[var(--muted)]" />
        <span className="min-w-0 flex-1 truncate font-medium" title={d.label}>
          {d.label}
        </span>
      </div>
      {d.host && (
        <span className="truncate font-mono text-[9px] text-[var(--muted)]" title={d.host}>
          {d.host}
        </span>
      )}
      <Handle id="lt" type="target" position={Position.Left} style={{ ...HANDLE, opacity: 0.9, background: "#8b949e" }} />
    </div>
  )
}

// A deployment on another castle node (mesh-discovered). Read-only — you manage
// remote deployments from that node.
function RemoteNode({ data }: NodeProps) {
  const d = data as {
    label: string
    kind: string
    sub?: string
    launchUrl?: string
    focusDim?: boolean
    focused?: boolean
  }
  const color = KIND_COLOR[d.kind] ?? "#8b949e"
  return (
    <div
      className="group relative flex w-[132px] items-stretch overflow-hidden rounded-md border border-dashed bg-[var(--card)] text-xs"
      style={{
        borderColor: color,
        opacity: d.focusDim ? 0.12 : 0.9,
        boxShadow: d.focused ? `0 0 0 2px ${color}` : undefined,
      }}
      title="remote (on another node)"
    >
      {d.launchUrl && (
        <a
          href={d.launchUrl}
          target="_blank"
          rel="noreferrer"
          className="absolute right-0.5 top-0.5 z-10 rounded bg-[var(--card)]/80 p-0.5 text-[var(--muted)] opacity-0 hover:text-[var(--primary)] group-hover:opacity-100"
          title={`Launch ${d.launchUrl}`}
          onClick={(e) => e.stopPropagation()}
        >
          <ExternalLink size={12} />
        </a>
      )}
      <div className="w-1 shrink-0" style={{ background: color }} />
      <div className="min-w-0 flex-1 px-2 py-1">
        <div className="truncate text-[var(--card-foreground)]" title={d.label}>
          {d.label}
        </div>
        {d.sub && <div className="truncate text-[9px] text-[var(--muted)]">{d.sub}</div>}
      </div>
      <Handle id="rs" type="source" position={Position.Bottom} isConnectable={false} style={{ ...HANDLE, opacity: 0 }} />
      <Handle id="lt" type="target" position={Position.Left} isConnectable={false} style={{ ...HANDLE, opacity: 0 }} />
    </div>
  )
}

const nodeTypes = {
  map: MapNode,
  hub: HubNode,
  lane: LaneNode,
  program: ProgramNode,
  external: ExternalNode,
  remote: RemoteNode,
  divider: DividerNode,
}

interface Consume {
  id: string
  name: string
  kind: string
  external: boolean
  host?: string
  protocol: string
  node: string | null
  alternatives: string[]
}
interface Dependent {
  id: string
  name: string
  kind: string
  node: string | null
}
interface NodeMeta {
  label: string
  kind: string
  remote: boolean
  node: string | null
  reach: string | null
  exposable: boolean
  launchUrl?: string
}
interface Built {
  nodes: Node[]
  edges: Edge[]
  kindOf: Record<string, string>
  reachOf: Record<string, "internal" | "public">
  consumes: Map<string, Consume[]>
  consumedBy: Map<string, Dependent[]>
  meta: Map<string, NodeMeta>
}

interface MenuItem {
  label: string
  icon: typeof Globe
  danger?: boolean
  onClick: () => void
}

export function SystemMapPage() {
  const { data: graph, isLoading: graphLoading } = useGraph()
  const { data: jobs } = useJobs()
  const { data: programs } = usePrograms()
  const { data: gateway } = useGateway()
  const { data: suggestionsResp } = useSuggestions()
  const { data: meshResp } = useMeshDeployments()

  const setReach = useSetReach()
  const deleteDeployment = useDeleteDeployment()
  const serviceAction = useServiceAction()
  const mutateRequires = useMutateRequires()
  const saveReference = useSaveReference()
  const navigate = useNavigate()

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [banner, setBanner] = useState<{ type: "info" | "error"; text: string } | null>(null)
  const [confirmDel, setConfirmDel] = useState<{ name: string; kind: string } | null>(null)
  // Lasso mode: when on, a plain left-drag draws a selection box (pan moves to
  // middle/right mouse). When off, left-drag pans and Shift-drag still lassos.
  const [lasso, setLasso] = useState(false)
  // Inspect/focus: the single selected node whose consumes/consumed_by light up.
  const [focus, setFocus] = useState<string | null>(null)
  const [addExt, setAddExt] = useState(false)

  const openProgram = useCallback((program: string) => navigate(`/programs/${program}`), [navigate])
  const [searchParams] = useSearchParams()

  // Kind lookup for handlers (which config section to write). Kept in a ref so the
  // stable callbacks below don't need it in their dep arrays.
  const kindRef = useRef<Record<string, string>>({})
  const reachRef = useRef<Record<string, "internal" | "public">>({})
  const focusRef = useRef<string | null>(null)
  // True while a connection is being dragged — the resync must not replace nodes
  // mid-drag (a background refetch would otherwise silently abort the connection).
  const connectingRef = useRef(false)
  // Manual node positions (persisted), and the react-flow instance for fitView.
  const posRef = useRef<PosMap | null>(null)
  if (posRef.current == null) posRef.current = loadPositions()
  const rfRef = useRef<ReactFlowInstance<Node, Edge> | null>(null)

  const built = useMemo<Built>(() => {
    if (!graph)
      return { nodes: [], edges: [], kindOf: {}, reachOf: {}, consumes: new Map(), consumedBy: new Map(), meta: new Map() }

    const scheduleOf = new Map((jobs ?? []).map((j) => [j.id, j.schedule]))
    // A deployment only links to a program if that program actually exists in the
    // catalog (has source). Infra like mqtt/postgres are inline container/compose
    // services — the graph fills `.program` with the deployment's own name as a
    // fallback, but there's no ProgramSpec, so no grip/link.
    const catalog = new Set((programs ?? []).map((p) => p.id))
    const routes = gateway?.routes ?? []
    const exposed = new Set(routes.map((r) => r.name).filter(Boolean) as string[])
    const publicSet = new Set(
      routes.filter((r) => r.public_url).map((r) => r.name).filter(Boolean) as string[],
    )

    // Per-node lookups from the graph itself (authoritative for sockets/reach now).
    const byName = new Map(graph.nodes.map((n) => [n.name, n]))
    const epOf = new Map(graph.nodes.map((n) => [n.name, n.endpoints]))

    // A browser-launchable URL (the "Start Menu" open) — a frontend or an
    // http-exposed service served at <name>.<domain>. TCP/tools/jobs aren't.
    const domain = gateway?.domain ?? null
    const launchOf = (n: (typeof graph.nodes)[number]): string | undefined => {
      if (!domain || !n.reach || n.reach === "off") return undefined
      if (n.kind === "static") return `https://${n.name}.${domain}`
      if (n.kind === "service" && n.endpoints.some((e) => e.protocol === "http"))
        return `https://${n.name}.${domain}`
      return undefined
    }

    // Remote launch: <subdomain>.<node-domain>, using the node's own acme domain
    // carried in the mesh payload. References launch at their base_url.
    const remoteLaunchOf = (md: MeshDeployment): string | undefined => {
      if (md.kind === "reference") return md.base_url ?? undefined
      if (md.subdomain && md.domain) return `https://${md.subdomain}.${md.domain}`
      return undefined
    }

    // Consumption of an external `reference` renders as a chip on the consumer (not
    // a long cross-map edge). Collect them here, keyed by the consuming deployment.
    // A job shows its cron; everything else prefers its declared socket, else its
    // gateway http port. This is what makes raw-TCP infra (postgres :5432) visible.
    const subFor = (n: (typeof graph.nodes)[number]): string | undefined => {
      if (n.kind === "job") return scheduleOf.get(n.name) ?? undefined
      const ep = n.endpoints?.[0]
      return ep ? `:${ep.port}` : undefined
    }

    const kindOf: Record<string, string> = {}
    const perLane: Record<string, number> = {}
    const nodes: Node[] = graph.nodes
      .filter((n) => LANES[n.kind])
      .sort((a, b) => b.depended_on_by - a.depended_on_by || a.name.localeCompare(b.name))
      .map((n) => {
        const lane = LANES[n.kind]
        const row = (perLane[n.kind] = (perLane[n.kind] ?? 0) + 1) - 1
        kindOf[n.name] = n.kind
        return {
          id: n.name,
          type: "map",
          position: { x: lane.x, y: TOP + row * ROW_H },
          deletable: true,
          data: {
            label: n.name,
            kind: n.kind,
            sub: subFor(n),
            dim: lane.dim,
            exposable: !!lane.exposable,
            program: n.program && catalog.has(n.program) ? n.program : null,
            reach: n.reach,
            launchUrl: launchOf(n),
          },
        } satisfies Node
      })

    // Undeployed (source-only) programs — the drag-to-deploy palette. Today this
    // is usually empty (every program is deployed); render a placeholder so the
    // affordance is visible.
    const undeployed = (programs ?? []).filter((p) => (p.deployments?.length ?? 0) === 0)
    undeployed.forEach((p, i) => {
      nodes.push({
        id: `__prog_${p.id}__`,
        type: "program",
        position: { x: PROG_X, y: TOP + i * ROW_H },
        draggable: false,
        deletable: false,
        data: { label: p.id },
      })
    })
    if (undeployed.length === 0) {
      nodes.push({
        id: "__prog_empty__",
        type: "program",
        position: { x: PROG_X, y: TOP },
        selectable: false,
        draggable: false,
        deletable: false,
        data: { label: "", placeholder: true },
      })
    }

    // External resources (references) — the registry + drop targets in the External
    // zone. Consumption of one shows as a chip on the consumer (above), not a line.
    const refs = graph.nodes.filter((n) => n.kind === "reference")
    refs.forEach((n, i) => {
      kindOf[n.name] = "reference"
      nodes.push({
        id: n.name,
        type: "external",
        position: { x: EXTERNAL_X, y: TOP + i * ROW_H },
        deletable: true,
        data: { label: n.name, host: hostOf(n.base_url) },
      })
    })

    // Mesh-discovered deployments grouped by machine. Their nodes are built *below*
    // the local block (after we know where it ends), so the local node stays on top.
    const byMachine = new Map<string, MeshDeployment[]>()
    for (const md of meshResp?.deployments ?? []) {
      const arr = byMachine.get(md.node) ?? []
      arr.push(md)
      byMachine.set(md.node, arr)
    }
    const remoteId = (node: string, name: string) => `__remote_${node}_${name}__`
    const remoteInfo = new Map<string, { md: MeshDeployment; machine: string }>()

    const maxRows = Math.max(1, ...Object.values(perLane))
    const midY = TOP + ((maxRows - 1) * ROW_H) / 2
    // Gateway shows its host origin; Internet shows the public (tunnel) zone.
    const gwHost = gateway?.domain ?? (gateway?.hostname ? `${gateway.hostname}:${gateway.port}` : null)
    const hubs: [string, number, "gateway" | "internet", string, string | null][] = [
      ["__gateway__", GATEWAY_X, "gateway", "LAN", gwHost],
      ["__internet__", INTERNET_X, "internet", "Internet", gateway?.public_domain ?? null],
    ]
    for (const [id, x, kind, label, sub] of hubs) {
      nodes.push({
        id,
        type: "hub",
        position: { x, y: midY },
        deletable: false,
        data: { label, kind, sub },
      })
    }

    const headers: [number, string][] = [
      [PROG_X, "Programs"],
      ...Object.values(LANES).map((l) => [l.x, l.title] as [number, string]),
      [GATEWAY_X, "Exposure"],
      ...(refs.length ? ([[EXTERNAL_X, "External"]] as [number, string][]) : []),
    ]
    for (const [x, title] of headers) {
      nodes.push({
        id: `__lane_${title}__`,
        type: "lane",
        position: { x, y: TOP - 40 },
        data: { label: title },
        selectable: false,
        draggable: false,
        deletable: false,
      })
    }

    // Local node label (top), then — below its deployments — a divider and each
    // other machine as a band in the SAME columns (so cross-node edges align).
    nodes.push({
      id: "__machine_local__",
      type: "lane",
      position: { x: PROG_X, y: TOP - 62 },
      selectable: false,
      draggable: false,
      deletable: false,
      data: { label: `⬡ ${gateway?.hostname ?? "local"} · this node` },
    })
    const localBottom = TOP + maxRows * ROW_H
    if (byMachine.size > 0) {
      nodes.push({
        id: "__divider_machines__",
        type: "divider",
        position: { x: PROG_X, y: localBottom + 12 },
        selectable: false,
        draggable: false,
        deletable: false,
        data: { label: "other machines", width: EXTERNAL_X - PROG_X + 180 },
      })
    }
    let bandTop = localBottom + 54
    for (const [machine, deps] of byMachine) {
      const perLaneM: Record<string, number> = {}
      const laid = deps
        .filter((md) => LANES[md.kind])
        .map((md) => {
          const lane = LANES[md.kind]
          const row = (perLaneM[md.kind] = (perLaneM[md.kind] ?? 0) + 1) - 1
          return { md, x: lane.x, row }
        })
      const rows = Math.max(1, ...Object.values(perLaneM))
      nodes.push({
        id: `__machine_${machine}__`,
        type: "lane",
        position: { x: PROG_X, y: bandTop - 22 },
        selectable: false,
        draggable: false,
        deletable: false,
        data: { label: `⬡ ${machine}` },
      })
      for (const { md, x, row } of laid) {
        const id = remoteId(machine, md.name)
        remoteInfo.set(id, { md, machine })
        kindOf[id] = md.kind
        nodes.push({
          id,
          type: "remote",
          position: { x, y: bandTop + row * ROW_H },
          selectable: true,
          draggable: true,
          deletable: false,
          data: {
            label: md.name,
            kind: md.kind,
            sub: md.endpoints[0] ? `:${md.endpoints[0].port}` : undefined,
            launchUrl: remoteLaunchOf(md),
          },
        })
      }
      bandTop += rows * ROW_H + 54
    }

    const present = new Set(nodes.map((n) => n.id))
    const edges: Edge[] = []

    for (const e of graph.edges) {
      if (e.kind !== "deployment") continue
      if (!present.has(e.src)) continue
      if (byName.get(e.dst)?.kind === "reference") continue // shown as a chip, not a line
      if (!present.has(e.dst)) continue
      // The edge inherits the protocol of the thing being consumed (target socket).
      const proto = epOf.get(e.dst)?.[0]?.protocol ?? "system"
      const color = PROTO_COLOR[proto] ?? PROTO_COLOR.system
      edges.push({
        id: `dep:${e.src}->${e.dst}`,
        source: e.src,
        target: e.dst,
        sourceHandle: "ls",
        targetHandle: "rt",
        label: e.bind ? `${proto} · ${e.bind}` : proto,
        deletable: true,
        data: { protocol: proto },
        style: { stroke: color, strokeWidth: 1.5 },
        labelStyle: { fill: color, fontSize: 10 },
        labelBgStyle: { fill: "#0d1117" },
      })
    }

    // "Same program" links — a program realized as more than one deployment (e.g.
    // protonmail as a tool AND a job) draws a dashed link between its siblings.
    const byProgram = new Map<string, string[]>()
    for (const n of graph.nodes) {
      if (!n.program || !present.has(n.name) || !LANES[n.kind]) continue
      const arr = byProgram.get(n.program) ?? []
      arr.push(n.name)
      byProgram.set(n.program, arr)
    }
    for (const [program, members] of byProgram) {
      if (members.length < 2) continue
      const ordered = [...members].sort((a, b) => LANES[kindOf[a]].x - LANES[kindOf[b]].x)
      for (let i = 0; i < ordered.length - 1; i++) {
        edges.push({
          id: `prog:${program}:${ordered[i]}-${ordered[i + 1]}`,
          source: ordered[i],
          target: ordered[i + 1],
          sourceHandle: "rs",
          targetHandle: "lt",
          label: program,
          deletable: false,
          style: { stroke: "#bc8cff", strokeWidth: 1.25, strokeDasharray: "4 3" },
          labelStyle: { fill: "#bc8cff", fontSize: 10 },
          labelBgStyle: { fill: "#0d1117" },
        })
      }
    }

    // Reach is modal: one line per exposed node. public → a single green line to
    // Internet; internal → a single blue line to Gateway. Dragging a new line to
    // the other target switches the mode; deleting the line removes exposure.
    const reachOf: Record<string, "internal" | "public"> = {}
    for (const name of exposed) {
      if (!present.has(name)) continue
      const isPub = publicSet.has(name)
      reachOf[name] = isPub ? "public" : "internal"
      edges.push({
        id: `exp:${name}`,
        source: name,
        target: isPub ? "__internet__" : "__gateway__",
        sourceHandle: "rs",
        targetHandle: "lt",
        animated: true,
        deletable: true,
        style: { stroke: isPub ? "#2ea043" : "#58a6ff", strokeWidth: 1.75 },
      })
    }

    // Suggested (undeclared) consumption — dashed amber, click to accept. Advisory:
    // derived from env, never written until you accept (which declares a requires).
    for (const s of suggestionsResp?.suggestions ?? []) {
      if (!present.has(s.consumer) || !present.has(s.provider)) continue
      edges.push({
        id: `sug:${s.consumer}->${s.provider}`,
        source: s.consumer,
        target: s.provider,
        sourceHandle: "ls",
        targetHandle: "rt",
        label: `suggest: ${s.env_var}`,
        deletable: false,
        style: { stroke: "#f59e0b", strokeWidth: 1.5, strokeDasharray: "5 4" },
        labelStyle: { fill: "#f59e0b", fontSize: 9 },
        labelBgStyle: { fill: "#0d1117" },
      })
    }

    // Cross-node consumption — a remote deployment's `requires` resolved against
    // the provider set across nodes: same machine first, then a local provider
    // (a cross-machine edge), then another machine. This is the multi-node payoff.
    const meshDeps = meshResp?.deployments ?? []
    const meshByNode = new Map<string, Set<string>>()
    for (const md of meshDeps) {
      const s = meshByNode.get(md.node) ?? new Set<string>()
      s.add(md.name)
      meshByNode.set(md.node, s)
    }
    // Cross-node relations (source id → target id), also fed into the focus adjacency.
    const xrel: [string, string][] = []
    for (const md of meshDeps) {
      for (const ref of md.requires ?? []) {
        let target: string | null = null
        if (meshByNode.get(md.node)?.has(ref) && present.has(remoteId(md.node, ref)))
          target = remoteId(md.node, ref) // same machine
        else if (present.has(ref))
          target = ref // a local provider — cross-machine edge
        else
          for (const [mn, names] of meshByNode)
            if (mn !== md.node && names.has(ref) && present.has(remoteId(mn, ref))) {
              target = remoteId(mn, ref)
              break
            }
        if (!target) continue
        xrel.push([remoteId(md.node, md.name), target])
        edges.push({
          id: `xnode:${md.node}:${md.name}->${ref}`,
          source: remoteId(md.node, md.name),
          target,
          sourceHandle: "rs",
          targetHandle: "lt",
          animated: true,
          deletable: false,
          label: `${md.node} → ${ref}`,
          style: { stroke: "#e879f9", strokeWidth: 1.5, strokeDasharray: "6 3" },
          labelStyle: { fill: "#e879f9", fontSize: 9 },
          labelBgStyle: { fill: "#0d1117" },
        })
      }
    }

    // Unified focus adjacency over node IDs (local names + remote ids) so the
    // inspect panel + highlight work identically for local and remote nodes.
    const localByName = new Map(graph.nodes.map((n) => [n.name, n]))
    const infoOf = (id: string) => {
      const ln = localByName.get(id)
      if (ln)
        return { label: ln.name, kind: ln.kind, remote: false, node: null as string | null, endpoints: ln.endpoints, base_url: ln.base_url }
      const ri = remoteInfo.get(id)
      if (ri)
        return { label: ri.md.name, kind: ri.md.kind, remote: true, node: ri.machine, endpoints: ri.md.endpoints, base_url: ri.md.base_url }
      return null
    }
    // Providers of a distinctive (non-http) protocol, across all nodes — "alternatives".
    const provByProto = new Map<string, { label: string; node: string | null }[]>()
    const addProv = (proto: string, label: string, node: string | null) => {
      if (proto === "http") return
      const a = provByProto.get(proto) ?? []
      a.push({ label, node })
      provByProto.set(proto, a)
    }
    for (const n of graph.nodes) for (const ep of n.endpoints) addProv(ep.protocol, n.name, null)
    for (const [, ri] of remoteInfo) for (const ep of ri.md.endpoints) addProv(ep.protocol, ri.md.name, ri.machine)

    type Consume = { id: string; name: string; kind: string; external: boolean; host?: string; protocol: string; node: string | null; alternatives: string[] }
    const consumes = new Map<string, Consume[]>()
    const consumedBy = new Map<string, { id: string; name: string; kind: string; node: string | null }[]>()
    const relate = (srcId: string, dstId: string) => {
      const si = infoOf(srcId)
      const di = infoOf(dstId)
      if (!si || !di) return
      const proto = di.base_url ? protoOf(di.base_url) : (di.endpoints?.[0]?.protocol ?? "system")
      const alts =
        proto === "http" || proto === "system"
          ? []
          : (provByProto.get(proto) ?? [])
              .filter((p) => p.label !== di.label)
              .map((p) => (p.node ? `${p.label} (${p.node})` : p.label))
      const cs = consumes.get(srcId) ?? []
      cs.push({ id: dstId, name: di.label, kind: di.kind, external: di.kind === "reference", host: di.base_url ? hostOf(di.base_url) : undefined, protocol: proto, node: di.node, alternatives: alts })
      consumes.set(srcId, cs)
      const cb = consumedBy.get(dstId) ?? []
      cb.push({ id: srcId, name: si.label, kind: si.kind, node: si.node })
      consumedBy.set(dstId, cb)
    }
    for (const e of graph.edges)
      if (e.kind === "deployment" && present.has(e.src) && present.has(e.dst)) relate(e.src, e.dst)
    for (const [s, d] of xrel) relate(s, d)

    const meta = new Map<string, NodeMeta>()
    for (const n of graph.nodes)
      meta.set(n.name, {
        label: n.name,
        kind: n.kind,
        remote: false,
        node: null,
        reach: n.reach,
        exposable: n.kind === "service" || n.kind === "static",
        launchUrl: n.kind === "reference" ? (n.base_url ?? undefined) : launchOf(n),
      })
    for (const [id, ri] of remoteInfo)
      meta.set(id, {
        label: ri.md.name,
        kind: ri.md.kind,
        remote: true,
        node: ri.machine,
        reach: null,
        exposable: false,
        launchUrl: remoteLaunchOf(ri.md),
      })

    return { nodes, edges, kindOf, reachOf, consumes, consumedBy, meta }
  }, [graph, jobs, programs, gateway, suggestionsResp, meshResp])

  // The lit neighborhood for the focused node: itself + everything it consumes +
  // everything that consumes it — from the unified adjacency, so local and remote
  // nodes behave identically. null = no focus.
  const litOf = useCallback(
    (f: string | null): Set<string> | null => {
      if (!f) return null
      const lit = new Set<string>([f])
      for (const c of built.consumes.get(f) ?? []) lit.add(c.id)
      for (const c of built.consumedBy.get(f) ?? []) lit.add(c.id)
      return lit
    },
    [built],
  )

  // Turn a Built into live nodes: inject the (stable) menu/program openers, override
  // positions with the saved layout, and apply focus dimming/highlight (via focusRef,
  // so the server-resync path re-reads current focus).
  const materialize = useCallback(
    (b: Built): Node[] => {
      const lit = litOf(focusRef.current)
      return b.nodes.map((n) => {
        const focusDim = lit ? !lit.has(n.id) : false
        const focused = n.id === focusRef.current
        const inspectable = n.type === "map" || n.type === "external" || n.type === "remote"
        let data = n.data
        if (n.type === "map") data = { ...data, onProgram: openProgram }
        if (inspectable) data = { ...data, focusDim, focused }
        // Keep the focused node selected across resyncs so inspect mode survives a
        // background refetch (otherwise react-flow clears selection → focus clears).
        return { ...n, position: posRef.current![n.id] ?? n.position, selected: focused, data }
      })
    },
    [openProgram, litOf],
  )

  // Dim edges not touching the focused node.
  const dimEdges = useCallback((es: Edge[]): Edge[] => {
    const f = focusRef.current
    return es.map((e) => ({
      ...e,
      style: { ...e.style, opacity: !f || e.source === f || e.target === f ? 1 : 0.07 },
    }))
  }, [])

  // Server is the source of truth: whenever derived data or focus changes, resync the
  // canvas (preserving the user's dragged positions via posRef). Interactions fire
  // mutations that invalidate the queries, which flow back through here.
  useEffect(() => {
    kindRef.current = built.kindOf
    reachRef.current = built.reachOf
    focusRef.current = focus
    // Don't rebuild the node/edge set while a connection is being dragged — replacing
    // the source node mid-drag silently cancels the connection (drag-to-expose "does
    // nothing"). The mutation that follows the drop re-syncs us anyway.
    if (connectingRef.current) return
    setNodes(materialize(built))
    // External consumption is drawn only while the consumer is selected — a dashed
    // line to each of its reference nodes (kept off-canvas otherwise to avoid a
    // permanent web of long cross-map lines).
    const extEdges: Edge[] = []
    if (focus && graph) {
      const refNames = new Set(
        graph.nodes.filter((n) => n.kind === "reference").map((n) => n.name),
      )
      for (const e of graph.edges) {
        if (e.kind === "deployment" && e.src === focus && refNames.has(e.dst)) {
          extEdges.push({
            id: `ext:${focus}->${e.dst}`,
            source: focus,
            target: e.dst,
            sourceHandle: "rs",
            targetHandle: "lt",
            animated: true,
            deletable: false,
            style: { stroke: "#8b949e", strokeWidth: 1.5, strokeDasharray: "4 3" },
          })
        }
      }
    }
    setEdges([...dimEdges(built.edges), ...extEdges])
  }, [built, focus, graph, setNodes, setEdges, materialize, dimEdges])

  // Single-node selection = inspect (dim + panel); 0 or many = no focus (drag mode).
  const onSelectionChange = useCallback((p: { nodes: Node[] }) => {
    const picks = p.nodes.filter((n) => n.type === "map" || n.type === "external" || n.type === "remote")
    setFocus(picks.length === 1 ? picks[0].id : null)
  }, [])

  // "Go to on map" from the command palette (/map?focus=<id>): select + center it.
  useEffect(() => {
    const f = searchParams.get("focus")
    if (!f) return
    const t = setTimeout(() => {
      setFocus(f)
      rfRef.current?.fitView({ nodes: [{ id: f }], padding: 0.6, duration: 400 })
    }, 200)
    return () => clearTimeout(t)
  }, [searchParams])

  // Remember where the user dropped a node (persist across refetches + reloads).
  const onNodeDragStop = useCallback((_e: MouseEvent | TouchEvent, _n: Node, dragged: Node[]) => {
    for (const nd of dragged) posRef.current![nd.id] = nd.position
    savePositions(posRef.current!)
  }, [])

  // Snap everything back to the computed lane layout.
  const resetLayout = useCallback(() => {
    posRef.current = {}
    savePositions({})
    setNodes(materialize(built))
    requestAnimationFrame(() => rfRef.current?.fitView({ padding: 0.1 }))
  }, [built, materialize, setNodes])

  const applyReach = useCallback(
    (name: string, kind: string, reach: "off" | "internal" | "public") => {
      setBanner({ type: "info", text: `${name} → reach: ${reach} — applying…` })
      setReach.mutate(
        { name, kind, reach },
        {
          onSuccess: () => setBanner({ type: "info", text: `${name} is now ${reach}.` }),
          onError: (e) =>
            setBanner({ type: "error", text: `${name}: ${e instanceof Error ? e.message : String(e)}` }),
        },
      )
    },
    [setReach],
  )

  // Declare / drop a `requires` edge (source requires target), then apply.
  const addDep = useCallback(
    (src: string, srcKind: string, dst: string) => {
      setBanner({ type: "info", text: `${src} → requires ${dst} — applying…` })
      mutateRequires.mutate(
        { name: src, kind: srcKind, add: dst },
        {
          onSuccess: () => setBanner({ type: "info", text: `${src} now requires ${dst}.` }),
          onError: (e) =>
            setBanner({ type: "error", text: `${src}: ${e instanceof Error ? e.message : String(e)}` }),
        },
      )
    },
    [mutateRequires],
  )
  const removeDep = useCallback(
    (src: string, srcKind: string, dst: string) => {
      setBanner({ type: "info", text: `${src} → drop requires ${dst} — applying…` })
      mutateRequires.mutate(
        { name: src, kind: srcKind, remove: dst },
        {
          onSuccess: () => setBanner({ type: "info", text: `${src} no longer requires ${dst}.` }),
          onError: (e) =>
            setBanner({ type: "error", text: `${src}: ${e instanceof Error ? e.message : String(e)}` }),
        },
      )
    },
    [mutateRequires],
  )

  // A dropped connection: onto a hub → set exposure; onto another deployment →
  // declare "source requires target".
  const onConnect = useCallback(
    (c: Connection) => {
      if (!c.source) return
      const kind = kindRef.current[c.source]
      if (!kind) return
      if (c.target === "__internet__") applyReach(c.source, kind, "public")
      else if (c.target === "__gateway__") applyReach(c.source, kind, "internal")
      else if (c.target && kindRef.current[c.target] && c.target !== c.source)
        addDep(c.source, kind, c.target)
    },
    [applyReach, addDep],
  )

  const onConnectStart = useCallback(() => {
    connectingRef.current = true
  }, [])
  // Re-sync on connect end (a refetch may have been skipped mid-drag).
  const onConnectEnd = useCallback(() => {
    connectingRef.current = false
    setNodes((ns) => [...ns])
  }, [setNodes])

  // Click a dashed amber suggestion to accept it → declares the requires.
  const onEdgeClick = useCallback(
    (_e: React.MouseEvent, edge: Edge) => {
      if (!edge.id.startsWith("sug:")) return
      const kind = kindRef.current[edge.source]
      if (kind) addDep(edge.source, kind, edge.target)
    },
    [addDep],
  )

  const isValidConnection = useCallback((c: Connection | Edge) => {
    const kind = c.source ? kindRef.current[c.source] : undefined
    if (!kind) return false
    // Exposure: only services/frontends, only onto a hub.
    if (c.target === "__internet__" || c.target === "__gateway__")
      return kind === "service" || kind === "static"
    // Dependency: onto any other deployment.
    return !!(c.target && kindRef.current[c.target]) && c.target !== c.source
  }, [])

  // Deleting a node's exposure line removes exposure: a service drops to off; a
  // static (always served) can't go off, so a public static drops to internal and
  // an internal one isn't deletable (blocked in onBeforeDelete).
  const onEdgesDelete = useCallback(
    (deleted: Edge[]) => {
      for (const e of deleted) {
        const kind = kindRef.current[e.source]
        if (!kind) continue
        if (e.id.startsWith("dep:")) {
          removeDep(e.source, kind, e.target)
        } else if (e.id.startsWith("exp:")) {
          if (kind === "static") {
            if (reachRef.current[e.source] === "public") applyReach(e.source, kind, "internal")
          } else {
            applyReach(e.source, kind, "off")
          }
        }
      }
    },
    [applyReach, removeDep],
  )

  // Intercept deletion: allow exposure edges through (onEdgesDelete handles them),
  // route node deletion to a confirm modal and block the immediate removal.
  const onBeforeDelete = useCallback(
    async ({ nodes: delNodes, edges: delEdges }: { nodes: Node[]; edges: Edge[] }) => {
      const target = delNodes.find((n) => n.type === "map" || n.type === "external")
      if (target) {
        const kind = kindRef.current[target.id]
        if (kind) setConfirmDel({ name: target.id, kind })
      }
      const allowedEdges = delEdges.filter((e) => {
        if (e.id.startsWith("dep:")) return true // remove a requires
        if (e.id.startsWith("exp:")) {
          // A static's internal line can't be removed — it's always served.
          if (kindRef.current[e.source] === "static") return reachRef.current[e.source] === "public"
          return true
        }
        return false // "same program" links aren't editable here
      })
      return { nodes: [], edges: allowedEdges }
    },
    [],
  )

  const doDelete = useCallback(() => {
    if (!confirmDel) return
    const { name, kind } = confirmDel
    setConfirmDel(null)
    setBanner({ type: "info", text: `Deleting ${name}…` })
    deleteDeployment.mutate(
      { name, kind },
      {
        onSuccess: () => setBanner({ type: "info", text: `Deleted ${name}.` }),
        onError: (e) =>
          setBanner({ type: "error", text: `${name}: ${e instanceof Error ? e.message : String(e)}` }),
      },
    )
  }, [confirmDel, deleteDeployment])

  const restart = useCallback(
    (name: string) => {
      setBanner({ type: "info", text: `Restarting ${name}…` })
      serviceAction.mutate(
        { name, action: "restart" },
        {
          onSuccess: () => setBanner({ type: "info", text: `${name} restarted.` }),
          onError: (err) =>
            setBanner({ type: "error", text: `${name}: ${err instanceof Error ? err.message : String(err)}` }),
        },
      )
    },
    [serviceAction],
  )

  // The inspected node's consumes / consumed_by — from the unified adjacency, so a
  // remote node's panel works identically to a local one.
  const focusInfo = useMemo(() => {
    if (!focus) return null
    const m = built.meta.get(focus)
    if (!m) return null
    return {
      id: focus,
      name: m.label,
      kind: m.kind,
      remote: m.remote,
      node: m.node,
      launchUrl: m.launchUrl,
      reach: m.reach,
      exposable: m.exposable,
      consumes: built.consumes.get(focus) ?? [],
      consumedBy: built.consumedBy.get(focus) ?? [],
    }
  }, [focus, built])

  // Actions for the inspected node — the old right-click menu, now in the panel.
  // Only for local (editable) deployments; remotes are view-only from here.
  const focusActions = useMemo<MenuItem[]>(() => {
    if (!focusInfo || focusInfo.remote) return []
    const { name, kind, reach, exposable } = focusInfo
    const items: MenuItem[] = []
    if (kind === "service") items.push({ label: "Restart", icon: RotateCw, onClick: () => restart(name) })
    if (exposable) {
      if (reach !== "public")
        items.push({ label: "Publish to internet", icon: Globe, onClick: () => applyReach(name, kind, "public") })
      if (reach !== "internal")
        items.push({ label: "Restrict to LAN", icon: Router, onClick: () => applyReach(name, kind, "internal") })
      if (kind === "service" && reach && reach !== "off")
        items.push({ label: "Make private (off)", icon: Lock, onClick: () => applyReach(name, kind, "off") })
    }
    items.push({ label: `Delete ${kind}`, icon: Trash2, danger: true, onClick: () => setConfirmDel({ name, kind }) })
    return items
  }, [focusInfo, restart, applyReach])

  const addExternal = useCallback(
    (name: string, base_url: string) => {
      setAddExt(false)
      setBanner({ type: "info", text: `Adding external ${name}…` })
      saveReference.mutate(
        { name, base_url },
        {
          onSuccess: () => setBanner({ type: "info", text: `External ${name} added.` }),
          onError: (e) =>
            setBanner({ type: "error", text: `${name}: ${e instanceof Error ? e.message : String(e)}` }),
        },
      )
    },
    [saveReference],
  )

  const detailPath = (name: string, kind: string) =>
    kind === "job" ? `/jobs/${name}` : kind === "tool" ? `/tools/${name}` : `/services/${name}`

  const busy =
    setReach.isPending ||
    deleteDeployment.isPending ||
    serviceAction.isPending ||
    mutateRequires.isPending ||
    saveReference.isPending

  return (
    <div className="h-[calc(100vh-3.5rem)] w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onConnectStart={onConnectStart}
        onConnectEnd={onConnectEnd}
        onEdgeClick={onEdgeClick}
        onNodeDragStop={onNodeDragStop}
        onEdgesDelete={onEdgesDelete}
        onBeforeDelete={onBeforeDelete}
        isValidConnection={isValidConnection}
        onInit={(inst) => (rfRef.current = inst)}
        onSelectionChange={onSelectionChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.1 }}
        deleteKeyCode={["Backspace", "Delete"]}
        nodesConnectable
        selectionOnDrag={lasso}
        panOnDrag={lasso ? [1, 2] : true}
        selectionMode={SelectionMode.Partial}
        selectionKeyCode="Shift"
        proOptions={{ hideAttribution: true }}
        colorMode="dark"
      >
        <Background color="#30363d" gap={20} />
        {(graphLoading || !graph) && (
          <div className="absolute inset-0 z-20 flex items-center justify-center gap-2 text-sm text-[var(--muted)]">
            <Loader2 size={18} className="animate-spin" />
            Loading map…
          </div>
        )}
        <Controls showInteractive={false}>
          <ControlButton
            onClick={() => setLasso((v) => !v)}
            title={lasso ? "Lasso select: on — drag to box-select (pan = middle/right mouse)" : "Lasso select: off — drag pans (Shift-drag to box-select)"}
            style={lasso ? { background: "var(--primary)", color: "#fff" } : undefined}
          >
            <BoxSelect size={12} />
          </ControlButton>
          <ControlButton onClick={resetLayout} title="Reset layout">
            <LayoutGrid size={12} />
          </ControlButton>
          <ControlButton onClick={() => setAddExt(true)} title="Add external resource">
            <Plus size={12} />
          </ControlButton>
        </Controls>
        <Legend />
        {(banner || busy) && (
          <div
            className={`absolute right-3 top-3 z-10 flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${
              banner?.type === "error"
                ? "border-red-800 bg-red-900/40 text-red-200"
                : "border-[var(--border)] bg-[var(--card)]/95 text-[var(--card-foreground)]"
            }`}
          >
            {busy && <Loader2 size={13} className="animate-spin" />}
            {banner?.text ?? "Applying…"}
          </div>
        )}
      </ReactFlow>

      {focusInfo && (
        <InspectPanel
          info={focusInfo}
          actions={focusActions}
          onClose={() => setFocus(null)}
          onOpen={(name, kind, node) => navigate(node ? `/node/${node}` : detailPath(name, kind))}
          onUnlink={(ref) => removeDep(focusInfo.name, focusInfo.kind, ref)}
        />
      )}

      {addExt && <AddExternalModal onSave={addExternal} onCancel={() => setAddExt(false)} />}

      <ConfirmModal
        open={!!confirmDel}
        danger
        title={`Delete ${confirmDel?.name}?`}
        body={`This removes the ${confirmDel?.kind} deployment from castle.yaml and tears it down. The program's source is kept.`}
        confirmLabel="Delete"
        onConfirm={doDelete}
        onCancel={() => setConfirmDel(null)}
      />
    </div>
  )
}

const LEGEND_KEY = "castle-map-legend-open"

function Legend() {
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(LEGEND_KEY) !== "false"
    } catch {
      return true
    }
  })
  const toggle = () =>
    setOpen((o) => {
      const next = !o
      try {
        localStorage.setItem(LEGEND_KEY, String(next))
      } catch {
        /* storage disabled */
      }
      return next
    })
  const items = [
    { c: PROTO_COLOR.http, label: "consumes — http" },
    { c: PROTO_COLOR.pg, label: "consumes — pg / db" },
    { c: PROTO_COLOR.system, label: "consumes — other" },
    { c: "#bc8cff", label: "same program", dashed: true },
    { c: "#f59e0b", label: "suggested — click to accept", dashed: true },
    { c: "#e879f9", label: "cross-node", dashed: true },
    { c: "#58a6ff", label: "internal — LAN" },
    { c: "#2ea043", label: "public — internet" },
  ]
  return (
    <div className="absolute bottom-3 right-3 z-10 overflow-hidden rounded-md border border-[var(--border)] bg-[var(--card)]/90 text-[11px] text-[var(--muted)]">
      <button
        onClick={toggle}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide hover:text-[var(--card-foreground)]"
      >
        <ChevronDown size={12} className={`transition-transform ${open ? "" : "-rotate-90"}`} />
        Legend
      </button>
      {open && (
        <div className="flex flex-col gap-1.5 px-3 pb-2">
          {items.map((i) => (
            <div key={i.label} className="flex items-center gap-2">
              <span
                className="inline-block w-5 shrink-0"
                style={
                  i.dashed
                    ? { borderTop: `2px dashed ${i.c}` }
                    : { height: 2, borderRadius: 2, background: i.c }
                }
              />
              {i.label}
            </div>
          ))}
          <div className="mt-1 border-t border-[var(--border)] pt-1.5 leading-relaxed">
            Click a node to inspect its consumes / consumed-by.
            <br />
            Drag a node → <span className="text-[#2ea043]">Internet</span> to publish, →{" "}
            <span className="text-[#58a6ff]">LAN</span> for internal; drag node→node to add a consumes.
            <br />
            Select a line or node + <kbd className="rounded bg-black/40 px-1">Del</kbd> to remove.
          </div>
        </div>
      )}
    </div>
  )
}

// The inspect panel — a fixed right-side card listing the focused node's consumes
// (with protocol/external chips) and consumed-by, each removable/navigable.
function InspectPanel({
  info,
  actions,
  onClose,
  onOpen,
  onUnlink,
}: {
  info: {
    name: string
    kind: string
    remote: boolean
    node: string | null
    launchUrl?: string
    consumes: Consume[]
    consumedBy: Dependent[]
  }
  actions: MenuItem[]
  onClose: () => void
  onOpen: (name: string, kind: string, node: string | null) => void
  onUnlink: (ref: string) => void
}) {
  return (
    <div className="absolute right-3 top-3 z-20 flex max-h-[calc(100%-1.5rem)] w-64 flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)] text-xs shadow-xl">
      <div className="flex items-center gap-2 border-b border-[var(--border)] px-3 py-2">
        <span className="min-w-0 flex-1 truncate font-semibold text-[var(--card-foreground)]" title={info.name}>
          {info.name}
        </span>
        {info.node && (
          <span className="shrink-0 rounded bg-[#e879f9]/20 px-1 text-[9px] text-[#e879f9]" title="on another machine">
            {info.node}
          </span>
        )}
        <span className="shrink-0 rounded bg-black/30 px-1.5 py-0.5 text-[9px] uppercase text-[var(--muted)]">
          {info.kind}
        </span>
        {info.launchUrl && (
          <a
            href={info.launchUrl}
            target="_blank"
            rel="noreferrer"
            title={`Launch ${info.launchUrl}`}
            className="text-[var(--muted)] hover:text-[var(--primary)]"
          >
            <ExternalLink size={13} />
          </a>
        )}
        <button onClick={() => onOpen(info.name, info.kind, info.node)} title="Castle details" className="text-[var(--muted)] hover:text-[var(--card-foreground)]">
          <Maximize2 size={12} />
        </button>
        <button onClick={onClose} title="Close" className="text-[var(--muted)] hover:text-[var(--card-foreground)]">
          <X size={14} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
        {actions.length > 0 && (
          <PanelSection title="Actions">
            <div className="flex flex-wrap gap-1">
              {actions.map((a) => {
                const Icon = a.icon
                return (
                  <button
                    key={a.label}
                    onClick={a.onClick}
                    className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] transition-colors ${
                      a.danger
                        ? "border-red-900 text-red-400 hover:bg-red-900/30"
                        : "border-[var(--border)] text-[var(--card-foreground)] hover:border-[var(--primary)]"
                    }`}
                  >
                    <Icon size={11} />
                    {a.label}
                  </button>
                )
              })}
            </div>
          </PanelSection>
        )}
        <PanelSection title={`Consumes (${info.consumes.length})`}>
          {info.consumes.length === 0 && <Empty />}
          {info.consumes.map((c) => (
            <div key={c.id} className="group py-0.5">
              <div className="flex items-center gap-1.5">
                <span
                  className="shrink-0 rounded px-1 text-[9px] font-medium"
                  style={{ background: `${PROTO_COLOR[c.protocol] ?? PROTO_COLOR.system}33`, color: PROTO_COLOR[c.protocol] ?? PROTO_COLOR.system }}
                >
                  {c.protocol}
                </span>
                {c.external ? (
                  <span className="inline-flex min-w-0 flex-1 items-center gap-1 truncate text-[var(--muted)]" title={c.host}>
                    <ExternalLink size={10} className="shrink-0" />
                    {c.name}
                  </span>
                ) : (
                  <button
                    className="min-w-0 flex-1 truncate text-left text-[var(--card-foreground)] hover:underline"
                    onClick={() => onOpen(c.name, c.kind, c.node)}
                  >
                    {c.name}
                  </button>
                )}
                {c.node && (
                  <span className="shrink-0 rounded bg-[#e879f9]/20 px-1 text-[9px] text-[#e879f9]" title="on another machine">
                    {c.node}
                  </span>
                )}
                {!info.remote && (
                  <button
                    onClick={() => onUnlink(c.name)}
                    title="Remove this dependency"
                    className="shrink-0 text-[var(--muted)] opacity-0 hover:text-red-400 group-hover:opacity-100"
                  >
                    <X size={11} />
                  </button>
                )}
              </div>
              {c.alternatives.length > 0 && (
                <div className="pl-6 text-[9px] text-[var(--muted)]" title={`other ${c.protocol} providers`}>
                  alt: {c.alternatives.join(", ")}
                </div>
              )}
            </div>
          ))}
        </PanelSection>
        <PanelSection title={`Consumed by (${info.consumedBy.length})`}>
          {info.consumedBy.length === 0 && <Empty />}
          {info.consumedBy.map((c) => (
            <button
              key={c.id}
              className="flex w-full items-center gap-1.5 py-0.5 text-left text-[var(--card-foreground)] hover:underline"
              onClick={() => onOpen(c.name, c.kind, c.node)}
            >
              <span className="min-w-0 flex-1 truncate">{c.name}</span>
              {c.node && (
                <span className="shrink-0 rounded bg-[#e879f9]/20 px-1 text-[9px] text-[#e879f9]" title="on another machine">
                  {c.node}
                </span>
              )}
            </button>
          ))}
        </PanelSection>
      </div>
    </div>
  )
}

function PanelSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-2">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--muted)]">{title}</div>
      {children}
    </div>
  )
}

function Empty() {
  return <div className="text-[10px] italic text-[var(--muted)]">none</div>
}

// A small form to declare an external resource (a `reference` — name + base_url).
function AddExternalModal({
  onSave,
  onCancel,
}: {
  onSave: (name: string, base_url: string) => void
  onCancel: () => void
}) {
  const [name, setName] = useState("")
  const [url, setUrl] = useState("")
  const ok = /^[a-z0-9][a-z0-9-]*$/.test(name) && /^\w+:\/\//.test(url)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onCancel}>
      <div
        className="w-full max-w-sm rounded-lg border border-[var(--border)] bg-[var(--card)] p-5 text-sm"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-1 font-semibold">Add external resource</h3>
        <p className="mb-3 text-xs text-[var(--muted)]">
          An endpoint castle doesn&apos;t run (a SaaS API, a remote service). Draw a consumes edge to
          it from any deployment.
        </p>
        <label className="mb-1 block text-xs text-[var(--muted)]">Name</label>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="claude-api"
          className="mb-3 w-full rounded border border-[var(--border)] bg-black/30 px-2 py-1 font-mono text-xs focus:border-[var(--primary)] focus:outline-none"
        />
        <label className="mb-1 block text-xs text-[var(--muted)]">Base URL</label>
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://api.anthropic.com"
          className="mb-4 w-full rounded border border-[var(--border)] bg-black/30 px-2 py-1 font-mono text-xs focus:border-[var(--primary)] focus:outline-none"
        />
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted)] hover:border-[var(--primary)]"
          >
            Cancel
          </button>
          <button
            onClick={() => ok && onSave(name, url)}
            disabled={!ok}
            className="rounded bg-blue-700 px-3 py-1.5 text-xs text-white hover:bg-blue-600 disabled:opacity-40"
          >
            Add
          </button>
        </div>
      </div>
    </div>
  )
}
