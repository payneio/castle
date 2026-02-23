import { Link } from "react-router-dom"
import { ArrowLeft } from "lucide-react"
import { useTools } from "@/services/api/hooks"
import { ToolCard } from "@/components/ToolCard"

export function ToolsPage() {
  const { data: tools, isLoading } = useTools()

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <Link to="/" className="text-[var(--primary)] hover:underline flex items-center gap-1 mb-6">
        <ArrowLeft size={16} /> Back
      </Link>

      <h1 className="text-3xl font-bold mb-2">Tools</h1>
      <p className="text-sm text-[var(--muted)] mb-8">
        CLI utilities installed to PATH via castle and run with uv.
      </p>

      {isLoading ? (
        <p className="text-[var(--muted)]">Loading tools...</p>
      ) : tools?.length ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {tools.map((tool) => (
            <ToolCard key={tool.id} tool={tool} />
          ))}
        </div>
      ) : (
        <p className="text-[var(--muted)]">No tools registered.</p>
      )}
    </div>
  )
}
