import { useState } from "react"
import {
  FileCheck,
  FlaskConical,
  Hammer,
  Loader2,
  Plug,
  ShieldCheck,
  Sparkles,
  Unplug,
  type LucideIcon,
} from "lucide-react"
import { useProgramAction } from "@/services/api/hooks"

interface ActionConfig {
  icon: LucideIcon
  label: string
  color: string
  hoverBg: string
  borderColor: string
}

const ACTION_CONFIG: Record<string, ActionConfig> = {
  build:        { icon: Hammer,       label: "Build",      color: "text-blue-400",   hoverBg: "hover:bg-blue-800/30",   borderColor: "border-blue-800" },
  test:         { icon: FlaskConical, label: "Test",       color: "text-purple-400", hoverBg: "hover:bg-purple-800/30", borderColor: "border-purple-800" },
  lint:         { icon: Sparkles,     label: "Lint",       color: "text-amber-400",  hoverBg: "hover:bg-amber-800/30",  borderColor: "border-amber-800" },
  "type-check": { icon: FileCheck,    label: "Type Check", color: "text-cyan-400",   hoverBg: "hover:bg-cyan-800/30",   borderColor: "border-cyan-800" },
  check:        { icon: ShieldCheck,  label: "Check All",  color: "text-green-400",  hoverBg: "hover:bg-green-800/30",  borderColor: "border-green-800" },
  install:      { icon: Plug,         label: "Install",    color: "text-green-400",  hoverBg: "hover:bg-green-800/30",  borderColor: "border-green-800" },
  uninstall:    { icon: Unplug,       label: "Uninstall",  color: "text-red-400",    hoverBg: "hover:bg-red-800/30",    borderColor: "border-red-800" },
}

const DEV_ACTIONS = ["build", "test", "lint", "type-check", "check"]

export interface ActionOutput {
  action: string
  text: string
  ok: boolean
}

interface ProgramActionsProps {
  name: string
  actions: string[]
  active?: boolean | null
  kind?: string | null
  compact?: boolean
  onOutput?: (output: ActionOutput) => void
}

/** install/uninstall (activate) is meaningful only for a tool (a PATH deployment).
 * Services, jobs, and static (caddy) deployments are managed through their
 * deployment — never install/uninstall here. */
function showsActivation(kind: string | null | undefined): boolean {
  return kind === "tool"
}

function visibleActions(
  actions: string[],
  active: boolean | null | undefined,
  compact: boolean,
): string[] {
  // `active` is the uniform lifecycle state (on PATH / running / served), not a
  // PATH lookup — so it's correct for tools, services, jobs, and static frontends.
  if (compact) {
    // Table: only the activate/deactivate toggle based on state
    if (active === true) return actions.includes("uninstall") ? ["uninstall"] : []
    if (active === false) return actions.includes("install") ? ["install"] : []
    // null — show install if available
    return actions.includes("install") ? ["install"] : []
  }

  // Detail page: dev actions always, activate/deactivate based on state
  const visible: string[] = []
  for (const a of DEV_ACTIONS) {
    if (actions.includes(a)) visible.push(a)
  }
  if (active === true) {
    if (actions.includes("uninstall")) visible.push("uninstall")
  } else if (active === false) {
    if (actions.includes("install")) visible.push("install")
  } else {
    // null — show both if available
    if (actions.includes("install")) visible.push("install")
    if (actions.includes("uninstall")) visible.push("uninstall")
  }
  return visible
}

export function ProgramActions({
  name,
  actions,
  active,
  kind,
  compact,
  onOutput,
}: ProgramActionsProps) {
  const { mutate, isPending } = useProgramAction()
  const [runningAction, setRunningAction] = useState<string | null>(null)

  // Drop install/uninstall for kinds that activate via a deployment.
  const allowed = showsActivation(kind)
    ? actions
    : actions.filter((a) => a !== "install" && a !== "uninstall")
  const visible = visibleActions(allowed, active, !!compact)

  const handleAction = (action: string) => {
    setRunningAction(action)
    onOutput?.({ action: "", text: "", ok: true }) // clear previous
    mutate(
      { name, action },
      {
        onSuccess: (data) => {
          setRunningAction(null)
          if (!compact && DEV_ACTIONS.includes(action) && data.output) {
            onOutput?.({ action, text: data.output, ok: true })
          }
        },
        onError: (err) => {
          setRunningAction(null)
          if (!compact && DEV_ACTIONS.includes(action)) {
            let text = String(err)
            try {
              const parsed = JSON.parse((err as Error).message)
              text = parsed.detail ?? text
            } catch {
              text = (err as Error).message ?? text
            }
            onOutput?.({ action, text, ok: false })
          }
        },
      },
    )
  }

  if (visible.length === 0) return null

  return (
    <div className="flex items-center gap-1 flex-wrap">
      {visible.map((action) => {
        const config = ACTION_CONFIG[action]
        if (!config) return null
        const Icon = config.icon
        const isRunning = isPending && runningAction === action

        if (compact) {
          return (
            <button
              key={action}
              onClick={() => handleAction(action)}
              disabled={isPending}
              className={`p-1 rounded ${config.color} ${config.hoverBg} transition-colors disabled:opacity-40`}
              title={config.label}
            >
              {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Icon size={14} />}
            </button>
          )
        }

        return (
          <button
            key={action}
            onClick={() => handleAction(action)}
            disabled={isPending}
            className={`flex items-center gap-1.5 px-2 py-1 text-sm rounded border ${config.borderColor} ${config.color} ${config.hoverBg} transition-colors disabled:opacity-40`}
          >
            {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Icon size={14} />}
            {config.label}
          </button>
        )
      })}
    </div>
  )
}

export function ActionOutputPanel({ output, onDismiss }: { output: ActionOutput; onDismiss: () => void }) {
  if (!output.action) return null
  return (
    <div className={`rounded-lg border overflow-hidden ${output.ok ? "border-[var(--border)]" : "border-red-800"}`}>
      <div className={`flex items-center justify-between px-3 py-1.5 text-xs ${output.ok ? "text-green-400 bg-green-900/20" : "text-red-400 bg-red-900/20"}`}>
        <span>{ACTION_CONFIG[output.action]?.label ?? output.action} — {output.ok ? "ok" : "error"}</span>
        <button
          onClick={onDismiss}
          className="text-[var(--muted)] hover:text-[var(--foreground)]"
        >
          dismiss
        </button>
      </div>
      <pre className="p-3 text-xs font-mono text-gray-300 overflow-x-auto max-h-64 overflow-y-auto bg-black/40">
        {output.text}
      </pre>
    </div>
  )
}
