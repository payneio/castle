import { useMeshStatus, useNodes } from "@/services/api/hooks"
import { MeshPanel } from "@/components/MeshPanel"
import { NodeBar } from "@/components/NodeBar"
import { PageHeader } from "@/components/PageHeader"

export function MeshPage() {
  const { data: mesh, isLoading } = useMeshStatus()
  const { data: nodes } = useNodes()

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <PageHeader title="Mesh" subtitle="Multi-node discovery and coordination" />

      {nodes && <NodeBar nodes={nodes} />}

      {isLoading ? (
        <p className="text-[var(--muted)]">Loading...</p>
      ) : mesh?.enabled ? (
        <MeshPanel mesh={mesh} />
      ) : (
        <p className="text-[var(--muted)]">
          Mesh coordination is disabled on this node.
        </p>
      )}
    </div>
  )
}
