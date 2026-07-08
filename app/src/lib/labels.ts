import type { LucideIcon } from "lucide-react"
import { Box, Clock, LayoutTemplate, Package, Server, Waypoints, Wrench } from "lucide-react"

// Canonical kind → icon — the single source of truth so the nav, Overview tiles,
// cards, the System map, and the command palette all speak one visual language.
// (Colors live in KindBadge; labels/descriptions are below.) `program` is the
// catalog pseudo-kind, not a deployment kind — the same Package glyph the
// Programs nav entry and Overview tile use.
export const KIND_ICONS: Record<string, LucideIcon> = {
  service: Server,
  job: Clock,
  tool: Wrench,
  static: LayoutTemplate,
  reference: Waypoints,
  program: Package,
}

export function kindIcon(kind: string): LucideIcon {
  return KIND_ICONS[kind] ?? Box
}

export const LAUNCHER_LABELS: Record<string, string> = {
  python: "Python",
  command: "Command",
  container: "Container",
  compose: "Compose",
  node: "Node.js",
}

// Derived deployment kinds (service | job | tool | static | reference).
export const KIND_LABELS: Record<string, string> = {
  service: "Service",
  job: "Job",
  tool: "Tool",
  static: "Static",
  reference: "Reference",
}

export const KIND_DESCRIPTIONS: Record<string, string> = {
  service: "Long-running process (systemd)",
  job: "Scheduled task (timer)",
  tool: "CLI installed on PATH",
  static: "Static site served by the gateway",
  reference: "External service on another node",
}

export const STACK_LABELS: Record<string, string> = {
  "python-fastapi": "Python / FastAPI",
  "python-cli": "Python / CLI",
  "react-vite": "React / Vite",
  supabase: "Supabase",
  rust: "Rust",
  go: "Go",
  bash: "Bash",
  container: "Container",
  command: "Command",
  remote: "Remote",
}

export function launcherLabel(launcher: string): string {
  return LAUNCHER_LABELS[launcher] ?? launcher
}

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind
}

export function stackLabel(stack: string): string {
  return STACK_LABELS[stack] ?? stack
}

/**
 * The kind-scoped detail route for a deployment. A name can be shared across
 * kinds (a `backup` service + job + tool), so links must carry the kind to
 * reach the right twin. Statics share the service detail page.
 */
export function detailPath(name: string, kind: string): string {
  if (kind === "tool") return `/tools/${name}`
  if (kind === "job") return `/jobs/${name}`
  return `/services/${name}`
}

/**
 * Full URL for a service exposed at <subdomain>.<gateway.domain>. The domain is
 * derived from the dashboard's own host (it is served at castle.<domain>), so
 * this returns null when the dashboard is on a bare host (off mode, no subdomains).
 */
export function subdomainUrl(subdomain: string): string | null {
  if (typeof window === "undefined") return null
  const { protocol, hostname } = window.location
  const labels = hostname.split(".")
  if (labels.length <= 2) return null
  return `${protocol}//${subdomain}.${labels.slice(1).join(".")}`
}

/**
 * The concrete host a subdomain is exposed at — `<subdomain>.<domain>` — using
 * this node's configured gateway domain. Falls back to the literal
 * `<subdomain>.<gateway.domain>` placeholder only when no domain is configured
 * (off mode), so hints and previews show real values wherever one exists.
 */
export function gatewayHost(subdomain: string, domain?: string | null): string {
  return domain ? `${subdomain}.${domain}` : `${subdomain}.<gateway.domain>`
}

/** Same as {@link gatewayHost}, for the public (Cloudflare tunnel) zone. */
export function publicGatewayHost(subdomain: string, publicDomain?: string | null): string {
  return publicDomain ? `${subdomain}.${publicDomain}` : `${subdomain}.<gateway.public_domain>`
}
