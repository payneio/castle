export const RUNNER_LABELS: Record<string, string> = {
  python_uv_tool: "Python (uv)",
  command: "Command",
  python_module: "Python module",
  container: "Container",
  node: "Node.js",
  remote: "Remote",
}

export const TOOL_TYPE_LABELS: Record<string, string> = {
  python_standalone: "Python package",
  script: "Shell script",
}

export const ROLE_DESCRIPTIONS: Record<string, string> = {
  service: "Exposes HTTP endpoints",
  tool: "CLI utility installed to PATH",
  worker: "Background process (no HTTP)",
  job: "Runs on a schedule",
  frontend: "Built static assets",
  remote: "Hosted externally",
  containerized: "Runs in a container",
}

export function runnerLabel(runner: string): string {
  return RUNNER_LABELS[runner] ?? runner
}

export function toolTypeLabel(toolType: string): string {
  return TOOL_TYPE_LABELS[toolType] ?? toolType
}
