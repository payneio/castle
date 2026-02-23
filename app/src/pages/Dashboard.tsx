import { useMemo } from "react"
import { Link } from "react-router-dom"
import { useComponents, useStatus, useGateway, useNodes, useMeshStatus, useEventStream } from "@/services/api/hooks"
import { GatewayPanel } from "@/components/GatewayPanel"
import { MeshPanel } from "@/components/MeshPanel"
import { NodeBar } from "@/components/NodeBar"
import { ServiceSection } from "@/components/ServiceSection"
import { JobSection } from "@/components/JobSection"
import { ToolSection } from "@/components/ToolSection"
import { SectionHeader } from "@/components/SectionHeader"

export function Dashboard() {
  useEventStream()
  const { data: components, isLoading } = useComponents()
  const { data: statusResp } = useStatus()
  const { data: gateway } = useGateway()
  const { data: nodes } = useNodes()
  const { data: mesh } = useMeshStatus()

  const { services, jobs, tools, frontends, other } = useMemo(() => {
    const s = { services: [] as typeof components, jobs: [] as typeof components, tools: [] as typeof components, frontends: [] as typeof components, other: [] as typeof components }
    for (const c of components ?? []) {
      if (c.category === "service") s.services!.push(c)
      else if (c.category === "job") s.jobs!.push(c)
      else if (c.category === "tool") s.tools!.push(c)
      else if (c.category === "frontend") s.frontends!.push(c)
      else s.other!.push(c)
    }
    return { services: s.services!, jobs: s.jobs!, tools: s.tools!, frontends: s.frontends!, other: s.other! }
  }, [components])

  const statuses = statusResp?.statuses ?? []

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold">Castle</h1>
        <p className="text-[var(--muted)] mt-1">Personal software platform</p>
      </div>

      {nodes && <NodeBar nodes={nodes} />}

      {gateway && (
        <div className="mb-6">
          <GatewayPanel gateway={gateway} statuses={statuses} />
        </div>
      )}

      {mesh && (
        <div className="mb-10">
          <MeshPanel mesh={mesh} />
        </div>
      )}

      {isLoading ? (
        <p className="text-[var(--muted)]">Loading...</p>
      ) : (
        <div className="space-y-10">
          {services.length > 0 && (
            <ServiceSection services={services} statuses={statuses} />
          )}
          {jobs.length > 0 && (
            <JobSection jobs={jobs} />
          )}
          {tools.length > 0 && (
            <ToolSection tools={tools} />
          )}
          {frontends.length > 0 && (
            <section>
              <SectionHeader category="frontend" />
              <div className="border border-[var(--border)] rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <tbody>
                    {frontends.map((fe) => (
                      <tr key={fe.id} className="border-b border-[var(--border)] last:border-b-0 hover:bg-[var(--card)]/50 transition-colors">
                        <td className="px-3 py-2.5">
                          <Link
                            to={`/component/${fe.id}`}
                            className="font-medium hover:text-[var(--primary)] transition-colors"
                          >
                            {fe.id}
                          </Link>
                        </td>
                        <td className="px-3 py-2.5 text-[var(--muted)]">
                          {fe.description ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          {other.length > 0 && (
            <section>
              <SectionHeader category="component" />
              <div className="border border-[var(--border)] rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <tbody>
                    {other.map((c) => (
                      <tr key={c.id} className="border-b border-[var(--border)] last:border-b-0 hover:bg-[var(--card)]/50 transition-colors">
                        <td className="px-3 py-2.5">
                          <Link
                            to={`/component/${c.id}`}
                            className="font-medium hover:text-[var(--primary)] transition-colors"
                          >
                            {c.id}
                          </Link>
                        </td>
                        <td className="px-3 py-2.5 text-[var(--muted)]">
                          {c.description ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
