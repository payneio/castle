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

interface ProgramActionsProps {
  name: string
  actions: string[]
  installed?: boolean | null
  compact?: boolean
}

function visibleActions(
  actions: string[],
  installed: boolean | null | undefined,
  compact: boolean,
): string[] {
  if (compact) {
    // Table: only install/uninstall based on state
    if (installed === true) return actions.includes("uninstall") ? ["uninstall"] : []
    if (installed === false) return actions.includes("install") ? ["install"] : []
    // null — show install if available (frontends, etc.)
    return actions.includes("install") ? ["install"] : []
  }

  // Detail page: dev actions always, install/uninstall based on state
  const visible: string[] = []
  for (const a of DEV_ACTIONS) {
    if (actions.includes(a)) visible.push(a)
  }
  if (installed === true) {
    if (actions.includes("uninstall")) visible.push("uninstall")
  } else if (installed === false) {
    if (actions.includes("install")) visible.push("install")
  } else {
    // null — show both if available
    if (actions.includes("install")) visible.push("install")
    if (actions.includes("uninstall")) visible.push("uninstall")
  }
  return visible
}

export function ProgramActions({ name, actions, installed, compact }: ProgramActionsProps) {
  const { mutate, isPending } = useProgramAction()
  const [runningAction, setRunningAction] = useState<string | null>(null)
  const [output, setOutput] = useState<{ action: string; text: string; ok: boolean } | null>(null)

  const visible = visibleActions(actions, installed, !!compact)

  const handleAction = (action: string) => {
    setRunningAction(action)
    setOutput(null)
    mutate(
      { name, action },
      {
        onSuccess: (data) => {
          setRunningAction(null)
          // Show output for dev actions on detail page
          if (!compact && DEV_ACTIONS.includes(action) && data.output) {
            setOutput({ action, text: data.output, ok: true })
          }
        },
        onError: (err) => {
          setRunningAction(null)
          if (!compact && DEV_ACTIONS.includes(action)) {
            // Extract detail from API error JSON
            let text = String(err)
            try {
              const parsed = JSON.parse((err as Error).message)
              text = parsed.detail ?? text
            } catch {
              text = (err as Error).message ?? text
            }
            setOutput({ action, text, ok: false })
          }
        },
      },
    )
  }

  if (visible.length === 0) return null

  return (
    <div>
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

      {output && !compact && (
        <div className={`mt-3 rounded-lg border overflow-hidden ${output.ok ? "border-[var(--border)]" : "border-red-800"}`}>
          <div className={`flex items-center justify-between px-3 py-1.5 text-xs ${output.ok ? "text-green-400 bg-green-900/20" : "text-red-400 bg-red-900/20"}`}>
            <span>{ACTION_CONFIG[output.action]?.label ?? output.action} — {output.ok ? "ok" : "error"}</span>
            <button
              onClick={() => setOutput(null)}
              className="text-[var(--muted)] hover:text-[var(--foreground)]"
            >
              dismiss
            </button>
          </div>
          <pre className="p-3 text-xs font-mono text-gray-300 overflow-x-auto max-h-64 overflow-y-auto bg-black/40">
            {output.text}
          </pre>
        </div>
      )}
    </div>
  )
}
