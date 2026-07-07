import { useEffect, useRef, useState } from "react"
import { Check, ChevronsUpDown, ExternalLink, Hexagon } from "lucide-react"
import { useNodes } from "@/services/api/hooks"
import type { NodeSummary } from "@/types"
import { cn } from "@/lib/utils"

// Each machine's castle is served at its own origin (castle.<domain>), so hopping
// between hosts is a cross-origin navigation. This shows which host you're driving
// (the is_local node) and lets you jump to a peer's dashboard, preserving the view.
function dashboardUrl(n: NodeSummary): string {
  const base = n.gateway_domain
    ? `https://castle.${n.gateway_domain}`
    : `http://${n.hostname}:${n.gateway_port}`
  return `${base}${window.location.pathname}`
}

export function HostSwitcher({ collapsed }: { collapsed: boolean }) {
  const { data: nodes } = useNodes()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener("mousedown", onDown)
    return () => window.removeEventListener("mousedown", onDown)
  }, [open])

  const list = nodes ?? []
  const current = list.find((n) => n.is_local)
  const others = list.filter((n) => !n.is_local)
  const label = current?.hostname ?? "this node"
  const canSwitch = others.length > 0

  return (
    <div ref={ref} className="relative px-2 pt-2">
      <button
        onClick={() => canSwitch && setOpen((o) => !o)}
        title={collapsed ? `Host: ${label}` : canSwitch ? "Switch host" : `Host: ${label}`}
        className={cn(
          "flex w-full items-center gap-2 rounded-md border border-[var(--border)] px-2 py-1.5 text-sm",
          canSwitch ? "hover:bg-[var(--card)]" : "cursor-default",
          collapsed && "justify-center px-0",
        )}
      >
        <Hexagon size={16} className="shrink-0 text-[var(--primary)]" />
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1 truncate text-left font-medium text-[var(--foreground)]">
              {label}
            </span>
            {canSwitch && <ChevronsUpDown size={14} className="shrink-0 text-[var(--muted)]" />}
          </>
        )}
      </button>
      {open && (
        <div className="absolute left-2 z-50 mt-1 min-w-[190px] overflow-hidden rounded-md border border-[var(--border)] bg-[var(--card)] shadow-xl">
          <div className="border-b border-[var(--border)] px-2.5 py-1 text-[10px] uppercase tracking-wide text-[var(--muted)]">
            Castle hosts
          </div>
          {list.map((n) => {
            const isCur = n.is_local
            const inner = (
              <>
                <Hexagon
                  size={14}
                  className={cn("shrink-0", isCur ? "text-[var(--primary)]" : "text-[var(--muted)]")}
                />
                <span className="min-w-0 flex-1 truncate">{n.hostname}</span>
                {isCur ? (
                  <Check size={13} className="shrink-0 text-[var(--primary)]" />
                ) : (
                  <ExternalLink size={12} className="shrink-0 text-[var(--muted)]" />
                )}
              </>
            )
            const cls = "flex items-center gap-2 px-2.5 py-2 text-sm"
            if (isCur)
              return (
                <div key={n.hostname} className={cn(cls, "bg-[var(--primary)]/10")}>
                  {inner}
                </div>
              )
            return (
              <a
                key={n.hostname}
                href={dashboardUrl(n)}
                onClick={() => setOpen(false)}
                className={cn(cls, "hover:bg-white/5", !n.online && "opacity-40")}
              >
                {inner}
              </a>
            )
          })}
        </div>
      )}
    </div>
  )
}
