export const RUNNER_LABELS: Record<string, string> = {
  python: "Python",
  command: "Command",
  container: "Container",
  node: "Node.js",
  remote: "Remote",
}

export const BEHAVIOR_LABELS: Record<string, string> = {
  daemon: "Daemon",
  tool: "Tool",
  frontend: "Frontend",
}

export const BEHAVIOR_DESCRIPTIONS: Record<string, string> = {
  daemon: "Long-running process that exposes ports",
  tool: "CLI utility or scheduled task",
  frontend: "Built web application",
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

export const SECTION_HEADERS: Record<string, { title: string; subtitle: string }> = {
  service: { title: "Services", subtitle: "Long-running processes" },
  scheduled: { title: "Scheduled Jobs", subtitle: "Systemd timers" },
  program: { title: "Programs", subtitle: "Software catalog" },
}

export function runnerLabel(runner: string): string {
  return RUNNER_LABELS[runner] ?? runner
}

export function behaviorLabel(behavior: string): string {
  return BEHAVIOR_LABELS[behavior] ?? behavior
}

export function stackLabel(stack: string): string {
  return STACK_LABELS[stack] ?? stack
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
