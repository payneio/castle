export interface SystemdInfo {
  unit_name: string
  unit_path: string
  timer: boolean
}

export interface ComponentSummary {
  id: string
  description: string | null
  category: string
  runner: string | null
  port: number | null
  health_path: string | null
  proxy_path: string | null
  managed: boolean
  systemd: SystemdInfo | null
  version: string | null
  source: string | null
  system_dependencies: string[]
  schedule: string | null
  installed: boolean | null
  node: string | null
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

export interface GatewayRoute {
  path: string
  target_port: number
  component: string
  node: string
}

export interface GatewayInfo {
  port: number
  hostname: string
  component_count: number
  service_count: number
  managed_count: number
  routes: GatewayRoute[]
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

export interface NodeSummary {
  hostname: string
  gateway_port: number
  deployed_count: number
  service_count: number
  is_local: boolean
  online: boolean
  is_stale: boolean
  last_seen: number | null
}

export interface NodeDetail extends NodeSummary {
  deployed: ComponentSummary[]
}

export interface MeshStatus {
  enabled: boolean
  mqtt_connected: boolean
  mqtt_broker_host: string | null
  mqtt_broker_port: number | null
  mdns_enabled: boolean
  peer_count: number
  peers: string[]
}

export interface ToolSummary {
  id: string
  description: string | null
  source: string | null
  version: string | null
  runner: string | null
  system_dependencies: string[]
  installed: boolean
}

export interface ToolDetail extends ToolSummary {
  docs: string | null
}
