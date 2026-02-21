export interface ComponentSummary {
  id: string
  description: string | null
  roles: string[]
  runner: string | null
  port: number | null
  health_path: string | null
  proxy_path: string | null
  managed: boolean
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

export interface ToolInfo {
  command: string
  description: string
  category: string
  version: string
  system_dependencies: string[]
  script: string
}
