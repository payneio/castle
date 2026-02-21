export interface ComponentSummary {
  id: string
  description: string | null
  roles: string[]
  runner: string | null
  port: number | null
  health_path: string | null
  proxy_path: string | null
  managed: boolean
  category: string | null
  version: string | null
  tool_type: string | null
  source: string | null
  system_dependencies: string[]
  schedule: string | null
  installed: boolean | null
}

export interface ComponentDetail extends ComponentSummary {
  manifest: Record<string, unknown>
}

export interface HealthStatus {
  id: string
  status: "up" | "down" | "unknown"
  latency_ms: number | null
}

export interface StatusResponse {
  statuses: HealthStatus[]
}

export interface GatewayInfo {
  port: number
  component_count: number
  service_count: number
  managed_count: number
}

export interface ServiceActionResponse {
  component: string
  action: string
  status: string
}

export interface SSEHealthEvent {
  statuses: HealthStatus[]
  timestamp: number
}

export interface SSEServiceActionEvent {
  action: string
  component: string
  status: string
}

export interface ToolSummary {
  id: string
  description: string | null
  category: string | null
  source: string | null
  tool_type: string | null
  version: string | null
  runner: string | null
  system_dependencies: string[]
  installed: boolean
}

export interface ToolCategory {
  name: string
  tools: ToolSummary[]
}

export interface ToolDetail extends ToolSummary {
  docs: string | null
}
