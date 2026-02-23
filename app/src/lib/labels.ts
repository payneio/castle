export const RUNNER_LABELS: Record<string, string> = {
  python: "Python",
  command: "Command",
  container: "Container",
  node: "Node.js",
  remote: "Remote",
}

export const CATEGORY_LABELS: Record<string, string> = {
  service: "Services",
  job: "Jobs",
  tool: "Tools",
  frontend: "Frontends",
  component: "Components",
}

export const CATEGORY_DESCRIPTIONS: Record<string, string> = {
  service: "Long-running daemon",
  job: "Scheduled task",
  tool: "CLI utility installed to PATH",
  frontend: "Built static assets",
  component: "Software component",
}

export const SECTION_HEADERS: Record<string, { title: string; subtitle: string }> = {
  service: { title: "Services", subtitle: "Long-running daemons managed by systemd" },
  job: { title: "Jobs", subtitle: "Scheduled tasks with cron timers" },
  tool: { title: "Tools", subtitle: "CLI utilities installed to PATH" },
  frontend: { title: "Frontends", subtitle: "Built web applications" },
  component: { title: "Other", subtitle: "Software catalog entries" },
}

export function runnerLabel(runner: string): string {
  return RUNNER_LABELS[runner] ?? runner
}
