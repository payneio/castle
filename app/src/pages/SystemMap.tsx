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
import { useNavigate } from "react-router-dom"
import {
  BoxSelect,
  ExternalLink,
  Globe,
  LayoutGrid,
  Loader2,
  Lock,
  Minus,
  MoreVertical,
  Package,
  RotateCw,
  Router,
  Trash2,
} from "lucide-react"
import {
  useDeleteDeployment,
  useGateway,
  useGraph,
  useJobs,
  usePrograms,
  useServiceAction,
  useServices,
  useSetReach,
} from "@/services/api/hooks"
import { ConfirmModal } from "@/components/ConfirmModal"

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
function MapNode({ id, data }: NodeProps) {
  const d = data as {
    label: string
    kind: string
    sub?: string
    dim?: boolean
    hub?: number
    exposable?: boolean
    program?: string | null
    onMenu?: (x: number, y: number, name: string, kind: string) => void
    onProgram?: (program: string) => void
  }
  const color = KIND_COLOR[d.kind] ?? "#8b949e"
  return (
    <div
      className="group relative flex items-stretch overflow-hidden rounded-md border bg-[var(--card)] text-xs shadow-sm"
      style={{ borderColor: color, width: 156, opacity: d.dim ? 0.55 : 1 }}
    >
      <button
        className="absolute right-0.5 top-0.5 z-10 rounded bg-[var(--card)]/80 p-0.5 text-[var(--muted)] opacity-0 hover:text-[var(--card-foreground)] group-hover:opacity-100"
        title="Actions"
        onClick={(e) => {
          e.stopPropagation()
          const r = e.currentTarget.getBoundingClientRect()
          d.onMenu?.(r.right, r.bottom, id, d.kind)
        }}
      >
        <MoreVertical size={12} />
      </button>
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
        <div className="truncate font-medium text-[var(--card-foreground)]" title={d.label}>
          {d.label}
        </div>
        {d.sub && <div className="truncate text-[10px] text-[var(--muted)]">{d.sub}</div>}
        {typeof d.hub === "number" && d.hub > 0 && (
          <div className="text-[10px]" style={{ color }}>
            ← {d.hub} depend on this
          </div>
        )}
      </div>
      <Handle
        id="rs"
        type="source"
        position={Position.Right}
        isConnectable={!!d.exposable}
        style={{ ...HANDLE, opacity: d.exposable ? 0.9 : 0, background: color }}
      />
      <Handle id="lt" type="target" position={Position.Left} isConnectable={false} style={{ ...HANDLE, opacity: 0 }} />
      <Handle id="ls" type="source" position={Position.Left} isConnectable={false} style={{ ...HANDLE, opacity: 0 }} />
      <Handle id="rt" type="target" position={Position.Right} isConnectable={false} style={{ ...HANDLE, opacity: 0 }} />
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

const nodeTypes = { map: MapNode, hub: HubNode, lane: LaneNode, program: ProgramNode }

interface Built {
  nodes: Node[]
  edges: Edge[]
  kindOf: Record<string, string>
  reachOf: Record<string, "internal" | "public">
}

interface MenuItem {
  label: string
  icon: typeof Globe
  danger?: boolean
  onClick: () => void
}

export function SystemMapPage() {
  const { data: graph } = useGraph()
  const { data: services } = useServices()
  const { data: jobs } = useJobs()
  const { data: programs } = usePrograms()
  const { data: gateway } = useGateway()

  const setReach = useSetReach()
  const deleteDeployment = useDeleteDeployment()
  const serviceAction = useServiceAction()
  const navigate = useNavigate()

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [banner, setBanner] = useState<{ type: "info" | "error"; text: string } | null>(null)
  const [confirmDel, setConfirmDel] = useState<{ name: string; kind: string } | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number; name: string; kind: string } | null>(null)
  // Lasso mode: when on, a plain left-drag draws a selection box (pan moves to
  // middle/right mouse). When off, left-drag pans and Shift-drag still lassos.
  const [lasso, setLasso] = useState(false)

  const openMenu = useCallback(
    (x: number, y: number, name: string, kind: string) => setMenu({ x, y, name, kind }),
    [],
  )
  const openProgram = useCallback((program: string) => navigate(`/programs/${program}`), [navigate])

  // Kind lookup for handlers (which config section to write). Kept in a ref so the
  // stable callbacks below don't need it in their dep arrays.
  const kindRef = useRef<Record<string, string>>({})
  const reachRef = useRef<Record<string, "internal" | "public">>({})
  // Manual node positions (persisted), and the react-flow instance for fitView.
  const posRef = useRef<PosMap | null>(null)
  if (posRef.current == null) posRef.current = loadPositions()
  const rfRef = useRef<ReactFlowInstance<Node, Edge> | null>(null)

  const built = useMemo<Built>(() => {
    if (!graph) return { nodes: [], edges: [], kindOf: {}, reachOf: {} }

    const portOf = new Map((services ?? []).map((s) => [s.id, s.port]))
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

    // A job shows its cron; a service shows its port.
    const subFor = (n: (typeof graph.nodes)[number]): string | undefined => {
      if (n.kind === "job") return scheduleOf.get(n.name) ?? undefined
      const port = portOf.get(n.name)
      return port ? `:${port}` : undefined
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
            hub: n.depended_on_by,
            exposable: !!lane.exposable,
            program: n.program && catalog.has(n.program) ? n.program : null,
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

    const present = new Set(nodes.map((n) => n.id))
    const edges: Edge[] = []

    for (const e of graph.edges) {
      if (e.kind !== "deployment") continue
      if (!present.has(e.src) || !present.has(e.dst)) continue
      edges.push({
        id: `dep:${e.src}->${e.dst}`,
        source: e.src,
        target: e.dst,
        sourceHandle: "ls",
        targetHandle: "rt",
        label: e.bind ?? undefined,
        deletable: false,
        style: { stroke: "#6e7681", strokeWidth: 1.5 },
        labelStyle: { fill: "#8b949e", fontSize: 10 },
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
        animated: isPub,
        deletable: true,
        style: { stroke: isPub ? "#2ea043" : "#58a6ff", strokeWidth: 1.75 },
      })
    }

    return { nodes, edges, kindOf, reachOf }
  }, [graph, services, jobs, programs, gateway])

  // Turn a Built into live nodes: inject the (stable) menu/program openers into
  // deployment nodes, and override each position with the user's saved layout
  // (falling back to the computed lane position).
  const materialize = useCallback(
    (b: Built): Node[] =>
      b.nodes.map((n) => ({
        ...n,
        position: posRef.current![n.id] ?? n.position,
        data: n.type === "map" ? { ...n.data, onMenu: openMenu, onProgram: openProgram } : n.data,
      })),
    [openMenu, openProgram],
  )

  // Server is the source of truth: whenever derived data changes, resync the
  // canvas (preserving the user's dragged positions via posRef). Interactions fire
  // mutations that invalidate the queries, which flow back through here.
  useEffect(() => {
    kindRef.current = built.kindOf
    reachRef.current = built.reachOf
    setNodes(materialize(built))
    setEdges(built.edges)
  }, [built, setNodes, setEdges, materialize])

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

  // Drop a connection on a hub → set exposure. Anything else is ignored.
  const onConnect = useCallback(
    (c: Connection) => {
      if (!c.source) return
      const kind = kindRef.current[c.source]
      if (!kind) return
      if (c.target === "__internet__") applyReach(c.source, kind, "public")
      else if (c.target === "__gateway__") applyReach(c.source, kind, "internal")
    },
    [applyReach],
  )

  const isValidConnection = useCallback((c: Connection | Edge) => {
    const kind = c.source ? kindRef.current[c.source] : undefined
    const exposable = kind === "service" || kind === "static"
    return exposable && (c.target === "__internet__" || c.target === "__gateway__")
  }, [])

  // Deleting a node's exposure line removes exposure: a service drops to off; a
  // static (always served) can't go off, so a public static drops to internal and
  // an internal one isn't deletable (blocked in onBeforeDelete).
  const onEdgesDelete = useCallback(
    (deleted: Edge[]) => {
      for (const e of deleted) {
        if (!e.id.startsWith("exp:")) continue
        const kind = kindRef.current[e.source]
        if (kind === "static") {
          if (reachRef.current[e.source] === "public") applyReach(e.source, kind, "internal")
        } else {
          applyReach(e.source, kind, "off")
        }
      }
    },
    [applyReach],
  )

  // Intercept deletion: allow exposure edges through (onEdgesDelete handles them),
  // route node deletion to a confirm modal and block the immediate removal.
  const onBeforeDelete = useCallback(
    async ({ nodes: delNodes, edges: delEdges }: { nodes: Node[]; edges: Edge[] }) => {
      const target = delNodes.find((n) => n.type === "map")
      if (target) {
        const kind = kindRef.current[target.id]
        if (kind) setConfirmDel({ name: target.id, kind })
      }
      const allowedEdges = delEdges.filter((e) => {
        if (!e.id.startsWith("exp:")) return false
        // A static's internal line can't be removed — it's always served.
        if (kindRef.current[e.source] === "static") return reachRef.current[e.source] === "public"
        return true
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

  // Right-click a deployment → same menu as the hover kebab.
  const onNodeContextMenu = useCallback(
    (e: React.MouseEvent, node: Node) => {
      if (node.type !== "map") return
      e.preventDefault()
      openMenu(e.clientX, e.clientY, node.id, (node.data as { kind: string }).kind)
    },
    [openMenu],
  )

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

  // The menu's actions for the right-clicked/kebabbed deployment. Exposure items
  // are contextual on the current reach (from reachRef); statics are always served.
  const menuItems = useMemo<MenuItem[]>(() => {
    if (!menu) return []
    const { name, kind } = menu
    const close = () => setMenu(null)
    const path = kind === "job" ? `/jobs/${name}` : kind === "tool" ? `/tools/${name}` : `/services/${name}`
    const items: MenuItem[] = [
      { label: "Open", icon: ExternalLink, onClick: () => (close(), navigate(path)) },
    ]
    if (kind === "service") items.push({ label: "Restart", icon: RotateCw, onClick: () => (close(), restart(name)) })
    if (kind === "service" || kind === "static") {
      const reach = built.reachOf[name] // internal | public | undefined(off)
      if (reach !== "public")
        items.push({ label: "Publish to internet", icon: Globe, onClick: () => (close(), applyReach(name, kind, "public")) })
      if (reach !== "internal")
        items.push({ label: "Restrict to LAN", icon: Router, onClick: () => (close(), applyReach(name, kind, "internal")) })
      if (kind === "service" && reach)
        items.push({ label: "Make private (off)", icon: Lock, onClick: () => (close(), applyReach(name, kind, "off")) })
    }
    items.push({
      label: `Delete ${kind}`,
      icon: Trash2,
      danger: true,
      onClick: () => (close(), setConfirmDel({ name, kind })),
    })
    return items
  }, [menu, built, navigate, restart, applyReach])

  const busy = setReach.isPending || deleteDeployment.isPending || serviceAction.isPending

  return (
    <div className="h-[calc(100vh-3.5rem)] w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeContextMenu={onNodeContextMenu}
        onNodeDragStop={onNodeDragStop}
        onEdgesDelete={onEdgesDelete}
        onBeforeDelete={onBeforeDelete}
        isValidConnection={isValidConnection}
        onInit={(inst) => (rfRef.current = inst)}
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

      {menu && (
        <NodeMenu menu={menu} items={menuItems} onClose={() => setMenu(null)} />
      )}

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

// The deployment popup — a fixed-position action list at the cursor/kebab, with a
// backdrop that closes it. Clamped to stay on-screen.
function NodeMenu({
  menu,
  items,
  onClose,
}: {
  menu: { x: number; y: number; name: string; kind: string }
  items: MenuItem[]
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose()
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  const left = Math.min(menu.x, window.innerWidth - 200)
  const top = Math.min(menu.y, window.innerHeight - (items.length * 34 + 40))
  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} onContextMenu={(e) => (e.preventDefault(), onClose())} />
      <div
        className="fixed z-50 w-[186px] overflow-hidden rounded-md border border-[var(--border)] bg-[var(--card)] py-1 text-xs shadow-xl"
        style={{ left, top }}
      >
        <div className="truncate px-3 py-1.5 font-mono text-[10px] text-[var(--muted)]" title={menu.name}>
          {menu.name}
        </div>
        <div className="border-t border-[var(--border)]" />
        {items.map((it) => {
          const Icon = it.icon
          return (
            <button
              key={it.label}
              onClick={it.onClick}
              className={`flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors hover:bg-white/5 ${
                it.danger ? "text-red-400" : "text-[var(--card-foreground)]"
              }`}
            >
              <Icon size={13} />
              {it.label}
            </button>
          )
        })}
      </div>
    </>
  )
}

function Legend() {
  const items = [
    { c: "#6e7681", label: "requires (dependency)" },
    { c: "#bc8cff", label: "same program", dashed: true },
    { c: "#58a6ff", label: "internal — on your LAN" },
    { c: "#2ea043", label: "public — on the internet" },
  ]
  return (
    <div className="absolute bottom-3 right-3 z-10 flex flex-col gap-1.5 rounded-md border border-[var(--border)] bg-[var(--card)]/90 px-3 py-2 text-[11px] text-[var(--muted)]">
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
        Drag a node → <span className="text-[#2ea043]">Internet</span> to publish, →{" "}
        <span className="text-[#58a6ff]">LAN</span> for internal.
        <br />
        Select a line or node + <kbd className="rounded bg-black/40 px-1">Del</kbd> to remove.
        <br />
        <kbd className="rounded bg-black/40 px-1">Shift</kbd>-drag to box-select; drag any selected node to move them together.
      </div>
    </div>
  )
}
