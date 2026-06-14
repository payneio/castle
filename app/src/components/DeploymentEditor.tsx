import { useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"
import type { DeploymentDetail } from "@/types"
import { DeploymentFields } from "./DeploymentFields"
import { BehaviorBadge } from "./BehaviorBadge"
import { StackBadge } from "./StackBadge"

interface DeploymentEditorProps {
  deployment: DeploymentDetail
  onSave: (name: string, config: Record<string, unknown>) => Promise<void>
  onDelete: (name: string) => Promise<void>
}

export function DeploymentEditor({ deployment, onSave, onDelete }: DeploymentEditorProps) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          <span className="font-semibold">{deployment.id}</span>
          <span className="text-sm text-[var(--muted)]">{deployment.description}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <BehaviorBadge behavior={deployment.behavior} />
          <StackBadge stack={deployment.stack} />
        </div>
      </button>

      {expanded && (
        <div className="border-t border-[var(--border)] p-4">
          <DeploymentFields
            deployment={deployment}
            onSave={onSave}
            onDelete={onDelete}
          />
        </div>
      )}
    </div>
  )
}
