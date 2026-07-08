import { Link } from "react-router-dom"
import { Globe, Share2 } from "lucide-react"
import { KIND_ICONS } from "@/lib/labels"
import {
  useGateway,
  useJobs,
  useMeshStatus,
  useNodes,
  usePrograms,
  useServices,
  useStatus,
} from "@/services/api/hooks"
import { NodeBar } from "@/components/NodeBar"
import { PageHeader } from "@/components/PageHeader"
import { ConvergePanel } from "@/components/ConvergePanel"

export function Overview() {
  const { data: services } = useServices()
  const { data: jobs } = useJobs()
  const { data: tools } = usePrograms("tool")
  const { data: programs } = usePrograms()
  const { data: statusResp } = useStatus()
  const { data: gateway } = useGateway()
  const { data: mesh } = useMeshStatus()
  const { data: nodes } = useNodes()

  const statuses = statusResp?.statuses ?? []
  const upCount = (ids: string[]) =>
    statuses.filter((s) => ids.includes(s.id) && s.status === "up").length

  const serviceIds = (services ?? []).map((s) => s.id)
  const routeCount = gateway?.routes?.length ?? 0

  const tiles = [
    {
      to: "/services",
      icon: KIND_ICONS.service,
      label: "Services",
      value: services?.length ?? 0,
      detail: services ? `${upCount(serviceIds)} up` : "",
    },
    {
      to: "/scheduled",
      icon: KIND_ICONS.job,
      label: "Scheduled",
      value: jobs?.length ?? 0,
      detail: jobs ? `${jobs.length === 1 ? "job" : "jobs"}` : "",
    },
    {
      to: "/tools",
      icon: KIND_ICONS.tool,
      label: "Tools",
      value: tools?.length ?? 0,
      detail: tools ? "on PATH" : "",
    },
    {
      to: "/programs",
      icon: KIND_ICONS.program,
      label: "Programs",
      value: programs?.length ?? 0,
      detail: programs ? "in catalog" : "",
    },
    {
      to: "/gateway",
      icon: Globe,
      label: "Gateway",
      value: routeCount,
      detail: gateway ? `tls: ${gateway.tls ?? "off"}` : "",
    },
    {
      to: "/mesh",
      icon: Share2,
      label: "Mesh",
      value: mesh?.enabled ? mesh.peer_count : "—",
      detail: mesh?.enabled ? "peers" : "disabled",
    },
  ]

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <PageHeader title="Castle" subtitle="Personal software platform" />

      {nodes && <NodeBar nodes={nodes} />}

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
        {tiles.map(({ to, icon: Icon, label, value, detail }) => (
          <Link
            key={to}
            to={to}
            className="flex flex-col gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4 hover:border-[var(--primary)] transition-colors"
          >
            <div className="flex items-center gap-2 text-[var(--muted)]">
              <Icon size={16} />
              <span className="text-sm">{label}</span>
            </div>
            <div className="text-2xl font-bold">{value}</div>
            <div className="text-xs text-[var(--muted)]">{detail}</div>
          </Link>
        ))}
      </div>

      <ConvergePanel />
    </div>
  )
}
