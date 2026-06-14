export interface SystemdInfo {
  unit_name: string
  unit_path: string
  timer: boolean
}

export interface ServiceSummary {
  id: string
  description: string | null
  stack: string | null
  runner: string | null
  port: number | null
  health_path: string | null
  proxy_path: string | null
  managed: boolean
  systemd: SystemdInfo | null
  source: string | null
  node: string | null
}

export interface ServiceDetail extends ServiceSummary {
  manifest: Record<string, unknown>
}

export interface JobSummary {
  id: string
  description: string | null
  stack: string | null
  runner: string | null
  schedule: string | null
  managed: boolean
  systemd: SystemdInfo | null
  source: string | null
  node: string | null
}

export interface JobDetail extends JobSummary {
  manifest: Record<string, unknown>
}

export interface ProgramSummary {
  id: string
  description: string | null
  behavior: string | null
  stack: string | null
  runner: string | null
  version: string | null
  source: string | null
  repo: string | null
  ref: string | null
  commands: Record<string, string[][]> | null
  system_dependencies: string[]
  installed: boolean | null
  active: boolean | null
  actions: string[]
  node: string | null
}

export interface ProgramDetail extends ProgramSummary {
  manifest: Record<string, unknown>
}

// Union for shared detail components (ConfigPanel, ComponentFields)
export type AnyDetail = ServiceDetail | JobDetail | ProgramDetail

// Legacy unified type — kept for NodeDetail.deployed and compat endpoint
export interface DeploymentSummary {
  id: string
  category: "program" | "service" | "job" | null
  description: string | null
  behavior: string | null
  stack: string | null
  runner: string | null
  port: number | null
  health_path: string | null
  proxy_path: string | null
  managed: boolean
  systemd: SystemdInfo | null
  version: string | null
  source: string | null
  repo: string | null
  ref: string | null
  commands: Record<string, string[][]> | null
  system_dependencies: string[]
  schedule: string | null
  installed: boolean | null
  active: boolean | null
  node: string | null
}

export interface DeploymentDetail extends DeploymentSummary {
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
  program: string
  node: string
}

export interface GatewayInfo {
  port: number
  hostname: string
  deployment_count: number
  service_count: number
  managed_count: number
  routes: GatewayRoute[]
}

export interface ServiceActionResponse {
  program: string
  action: string
  status: string
}

export interface SSEHealthEvent {
  statuses: HealthStatus[]
  timestamp: number
}

export interface SSEServiceActionEvent {
  action: string
  program: string
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
  deployed: DeploymentSummary[]
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


