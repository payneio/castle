import { useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"
import type { ComponentDetail } from "@/types"
import { ComponentFields } from "./ComponentFields"
import { BehaviorBadge } from "./BehaviorBadge"
import { StackBadge } from "./StackBadge"

interface ComponentEditorProps {
  component: ComponentDetail
  onSave: (name: string, config: Record<string, unknown>) => Promise<void>
  onDelete: (name: string) => Promise<void>
}

export function ComponentEditor({ component, onSave, onDelete }: ComponentEditorProps) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          <span className="font-semibold">{component.id}</span>
          <span className="text-sm text-[var(--muted)]">{component.description}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <BehaviorBadge behavior={component.behavior} />
          <StackBadge stack={component.stack} />
        </div>
      </button>

      {expanded && (
        <div className="border-t border-[var(--border)] p-4">
          <ComponentFields
            component={component}
            onSave={onSave}
            onDelete={onDelete}
          />
        </div>
      )}
    </div>
  )
}
