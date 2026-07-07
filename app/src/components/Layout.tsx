import { useEffect, useState } from "react"
import { Link, NavLink, Outlet } from "react-router-dom"
import {
  Boxes,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  Globe,
  LayoutDashboard,
  Menu,
  Package,
  Search,
  Server,
  Share2,
  Map as MapIcon,
  Network,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useEventStream } from "@/services/api/hooks"
import { AssistantDock } from "@/components/AssistantDock"
import { CommandPalette } from "@/components/CommandPalette"

type NavLeaf = { to: string; label: string; icon: LucideIcon; end?: boolean }
type NavGroup = { label: string; icon: LucideIcon; children: NavLeaf[] }

// Services, Scheduled, and Tools are all deployment lenses — grouped under a
// "Deployments" parent. Programs (the catalog) stays top-level.
const NAV: (NavLeaf | NavGroup)[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/gateway", label: "Gateway", icon: Globe },
  {
    label: "Deployments",
    icon: Boxes,
    children: [
      { to: "/services", label: "Services", icon: Server },
      { to: "/scheduled", label: "Scheduled", icon: Clock },
      { to: "/tools", label: "Tools", icon: Wrench },
    ],
  },
  { to: "/programs", label: "Programs", icon: Package },
  { to: "/graph", label: "Graph", icon: Network },
  { to: "/map", label: "System Map", icon: MapIcon },
  { to: "/mesh", label: "Mesh", icon: Share2 },
]

const COLLAPSE_KEY = "castle-nav-collapsed"

function NavLeafLink({
  leaf,
  collapsed,
  indent,
  onNavigate,
}: {
  leaf: NavLeaf
  collapsed: boolean
  indent?: boolean
  onNavigate?: () => void
}) {
  const Icon = leaf.icon
  return (
    <NavLink
      to={leaf.to}
      end={leaf.end}
      onClick={onNavigate}
      title={collapsed ? leaf.label : undefined}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
          collapsed && "justify-center px-0",
          indent && !collapsed && "pl-9",
          isActive
            ? "bg-[var(--primary)]/10 text-[var(--foreground)] font-medium"
            : "text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--card)]",
        )
      }
    >
      <Icon size={18} className="shrink-0" />
      {!collapsed && <span>{leaf.label}</span>}
    </NavLink>
  )
}

function NavGroupItem({
  group,
  collapsed,
  onNavigate,
}: {
  group: NavGroup
  collapsed: boolean
  onNavigate?: () => void
}) {
  const [open, setOpen] = useState(true)
  // On the icon rail there's no room for a group header — show the children flat.
  if (collapsed) {
    return (
      <>
        {group.children.map((c) => (
          <NavLeafLink key={c.to} leaf={c} collapsed onNavigate={onNavigate} />
        ))}
      </>
    )
  }
  const Icon = group.icon
  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-3 rounded-md px-3 py-2 text-sm text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--card)] transition-colors"
      >
        <Icon size={18} className="shrink-0" />
        <span className="flex-1 text-left">{group.label}</span>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>
      {open && (
        <div className="mt-1 space-y-1">
          {group.children.map((c) => (
            <NavLeafLink key={c.to} leaf={c} collapsed={false} indent onNavigate={onNavigate} />
          ))}
        </div>
      )}
    </div>
  )
}

function NavItems({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  return (
    <nav className="flex-1 px-2 py-3 space-y-1 overflow-y-auto">
      <button
        onClick={() => {
          window.dispatchEvent(new Event("open-command-palette"))
          onNavigate?.()
        }}
        title="Launch or find anything (⌘K)"
        className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-[var(--muted)] hover:bg-white/5 hover:text-[var(--foreground)]"
      >
        <Search size={18} className="shrink-0" />
        {!collapsed && (
          <>
            <span className="flex-1 text-left">Launch…</span>
            <kbd className="rounded bg-black/40 px-1 text-[10px]">⌘K</kbd>
          </>
        )}
      </button>
      {NAV.map((item) =>
        "children" in item ? (
          <NavGroupItem key={item.label} group={item} collapsed={collapsed} onNavigate={onNavigate} />
        ) : (
          <NavLeafLink key={item.to} leaf={item} collapsed={collapsed} onNavigate={onNavigate} />
        ),
      )}
    </nav>
  )
}

function Brand({ collapsed, onClick }: { collapsed?: boolean; onClick?: () => void }) {
  return (
    <Link to="/" onClick={onClick} className="font-bold text-lg truncate">
      {collapsed ? "C" : "Castle"}
    </Link>
  )
}

export function Layout() {
  useEventStream()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === "1")
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0")
  }, [collapsed])

  return (
    <div className="min-h-screen bg-[var(--background)]">
      {/* Mobile top bar */}
      <header className="md:hidden fixed top-0 inset-x-0 h-14 z-40 flex items-center gap-3 px-4 border-b border-[var(--border)] bg-[var(--background)]">
        <button
          onClick={() => setMobileOpen(true)}
          aria-label="Open menu"
          className="text-[var(--muted)] hover:text-[var(--foreground)] transition-colors"
        >
          <Menu size={22} />
        </button>
        <Brand />
      </header>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="md:hidden fixed inset-0 z-50">
          <div className="absolute inset-0 bg-black/60" onClick={() => setMobileOpen(false)} />
          <aside className="absolute left-0 top-0 h-full w-64 flex flex-col bg-[var(--background)] border-r border-[var(--border)]">
            <div className="h-14 flex items-center justify-between px-4 border-b border-[var(--border)]">
              <Brand onClick={() => setMobileOpen(false)} />
              <button
                onClick={() => setMobileOpen(false)}
                aria-label="Close menu"
                className="text-[var(--muted)] hover:text-[var(--foreground)] transition-colors"
              >
                <X size={20} />
              </button>
            </div>
            <NavItems collapsed={false} onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      {/* Desktop sidebar */}
      <aside
        className={cn(
          "hidden md:flex fixed top-0 left-0 h-full flex-col border-r border-[var(--border)] bg-[var(--background)] transition-[width] duration-200",
          collapsed ? "w-16" : "w-56",
        )}
      >
        <div
          className={cn(
            "h-14 flex items-center border-b border-[var(--border)]",
            collapsed ? "justify-center" : "px-4",
          )}
        >
          <Brand collapsed={collapsed} />
        </div>
        <NavItems collapsed={collapsed} />
        <button
          onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? "Expand" : "Collapse"}
          className={cn(
            "h-12 flex items-center gap-3 border-t border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)] transition-colors",
            collapsed ? "justify-center" : "px-4",
          )}
        >
          {collapsed ? (
            <ChevronRight size={18} />
          ) : (
            <>
              <ChevronLeft size={18} />
              <span className="text-sm">Collapse</span>
            </>
          )}
        </button>
      </aside>

      {/* Main content */}
      <main
        className={cn(
          "min-w-0 pt-14 md:pt-0 transition-[padding] duration-200",
          collapsed ? "md:pl-16" : "md:pl-56",
        )}
      >
        <Outlet />
      </main>

      {/* Global assistant — persists across navigation (Layout doesn't remount). */}
      <AssistantDock />

      {/* App-wide ⌘K launcher / command palette. */}
      <CommandPalette />
    </div>
  )
}
