import { useEffect, useState } from "react"
import { Link, NavLink, Outlet } from "react-router-dom"
import {
  ChevronLeft,
  ChevronRight,
  Clock,
  Globe,
  LayoutDashboard,
  Menu,
  Package,
  Server,
  Share2,
  Wrench,
  X,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useEventStream } from "@/services/api/hooks"

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/gateway", label: "Gateway", icon: Globe, end: false },
  { to: "/services", label: "Services", icon: Server, end: false },
  { to: "/scheduled", label: "Scheduled", icon: Clock, end: false },
  { to: "/tools", label: "Tools", icon: Wrench, end: false },
  { to: "/programs", label: "Programs", icon: Package, end: false },
  { to: "/mesh", label: "Mesh", icon: Share2, end: false },
]

const COLLAPSE_KEY = "castle-nav-collapsed"

function NavItems({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  return (
    <nav className="flex-1 px-2 py-3 space-y-1 overflow-y-auto">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          title={collapsed ? label : undefined}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
              collapsed && "justify-center px-0",
              isActive
                ? "bg-[var(--primary)]/10 text-[var(--foreground)] font-medium"
                : "text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--card)]",
            )
          }
        >
          <Icon size={18} className="shrink-0" />
          {!collapsed && <span>{label}</span>}
        </NavLink>
      ))}
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
    </div>
  )
}
