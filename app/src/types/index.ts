export interface SystemdInfo {
  unit_name: string
  unit_path: string
  timer: boolean
}

export interface ServiceSummary {
  id: string
  description: string | null
  stack: string | null
  kind: string | null // service | static
  manager: string | null // systemd | caddy
  launcher: string | null // python | command | container | compose | node (systemd only)
  run_target: string | null
  port: number | null
  health_path: string | null
  subdomain: string | null // exposed at <subdomain>.<gateway.domain>, else null
  managed: boolean
  systemd: SystemdInfo | null
  program: string | null
  source: string | null
  enabled: boolean // declared desired state; `apply` converges to it
  node: string | null
}

export interface ServiceDetail extends ServiceSummary {
  manifest: Record<string, unknown>
}

export interface JobSummary {
  id: string
  description: string | null
  stack: string | null
  launcher: string | null // python | command | container | compose | node
  run_target: string | null
  schedule: string | null
  managed: boolean
  systemd: SystemdInfo | null
  program: string | null
  source: string | null
  enabled: boolean // declared desired state; `apply` converges to it
  node: string | null
}

export interface JobDetail extends JobSummary {
  manifest: Record<string, unknown>
}

// A program's deployment (name + its derived kind). A program has no kind of its
// own — it has deployments, each with a kind (a program can be a tool AND a job).
export interface DeploymentRef {
  name: string
  kind: string // service | job | tool | static | reference
}

export interface ProgramSummary {
  id: string
  description: string | null
  stack: string | null
  version: string | null
  source: string | null
  repo: string | null
  ref: string | null
  commands: Record<string, string[][]> | null
  system_dependencies: string[]
  installed: boolean | null
  active: boolean | null
  actions: string[]
  deployments: DeploymentRef[]
  node: string | null
}

export interface ProgramDetail extends ProgramSummary {
  manifest: Record<string, unknown>
}

// Git state of a program's source working copy (GET /programs/{name}/git).
// ahead/behind are relative to the upstream tracking branch (null = no upstream);
// behind reflects the fetch the status call performed.
export interface GitStatus {
  is_repo: boolean
  branch: string | null
  upstream: string | null
  dirty: boolean
  ahead: number | null
  behind: number | null
  detached: boolean
  error: string | null
  // The repo (git working copy) this program's source lives in. `multi` marks a
  // monorepo shared by several programs — sync operates on the whole repo.
  repo?: {
    key: string
    programs: string[]
    multi: boolean
    deployments: string[]
  } | null
}

// GET /repos — a repo (git working copy) with its members and last-known git state.
export interface RepoSummary {
  key: string
  path: string
  url: string | null
  ref: string | null
  programs: string[]
  deployments: string[]
  branch: string | null
  behind: number | null
  dirty: boolean
}

// GET /graph — the derived relationship model (docs/relationships.md).
export interface GraphRepo {
  key: string
  path: string
  url: string | null
  ref: string | null
  programs: string[]
  deployments: string[]
  behind: number | null
  dirty: boolean
  fresh: boolean | null
}
export interface GraphEndpoint {
  protocol: string // http | tcp | pg | bolt | mqtt | redis (display heuristic)
  port: number
}
export interface GraphNode {
  name: string
  program: string | null
  kind: string
  repo: string | null
  depended_on_by: number
  unmet: string[]
  functional: boolean
  fresh: boolean | null
  deployed: boolean | null
  reach: "off" | "internal" | "public" | null
  endpoints: GraphEndpoint[]
  base_url: string | null // set for kind === "reference" (external resource)
  provides: string[] // capability types this offers (from its program)
  consumes: string[] // capability types it needs (from its program)
}
export interface GraphEdge {
  src: string
  dst: string
  kind: "system" | "deployment"
  bind: string | null
}
export interface GraphModel {
  repos: GraphRepo[]
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// GET /graph/suggestions — undeclared consumption inferred from env endpoint values
// (an advisory; accepting one declares a real `requires`).
export interface GraphSuggestion {
  consumer: string
  provider: string
  env_var: string
  endpoint: string
  protocol: string
}

// GET /mesh/deployments — deployments on other (mesh-discovered) castle nodes.
export interface MeshDeployment {
  name: string
  kind: string
  node: string // the remote hostname
  domain: string | null // the node's gateway acme domain — for <subdomain>.<domain> launch URLs
  port: number | null
  base_url: string | null
  subdomain: string | null
  endpoints: GraphEndpoint[]
  requires: string[] // deployment refs it consumes (for cross-node edges)
}

// POST /programs/{name}/sync — a fast-forward pull (no build/apply/restart).
export interface ProgramSyncResponse {
  program: string
  status: string
  output: string
  pulled: boolean
  deployments: string[] // affected deployments that may need restart/apply
}

// Union for the shared ConfigPanel (ProgramFields / ServiceFields / JobFields)
export type AnyDetail = ServiceDetail | JobDetail | ProgramDetail

// Legacy unified type — kept for NodeDetail.deployed and compat endpoint
export interface DeploymentSummary {
  id: string
  category: "program" | "service" | "job" | null
  description: string | null
  kind: string | null // derived: service | job | tool | static | reference
  stack: string | null
  manager: string | null // systemd | caddy | path | none
  launcher: string | null // python | command | container | compose | node (systemd only)
  port: number | null
  health_path: string | null
  subdomain: string | null // exposed at <subdomain>.<gateway.domain>, else null
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
  enabled: boolean // declared desired state; `apply` converges to it
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
  address: string // "/foo" (path prefix) or "foo.lan" (host)
  kind: "static" | "proxy" | "remote"
  target: string // serve dir, "localhost:PORT", or "host:PORT"
  name: string | null
  node: string
  public_url?: string | null // set when the service is public (via the tunnel)
}

export interface GatewayInfo {
  port: number
  hostname: string
  deployment_count: number
  service_count: number
  managed_count: number
  routes: GatewayRoute[]
  tls?: string | null // "acme" → host routes served over HTTPS with a Let's Encrypt wildcard
  domain?: string | null // acme zone → <service>.<domain>
  public_domain?: string | null // tunnel zone → <service>.<public_domain>
  tunnel_id?: string | null
  tunnel_connected?: boolean
}

export interface GatewayConfigRequest {
  tls?: string | null
  domain?: string | null
  public_domain?: string | null
  tunnel_id?: string | null
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

// Agent terminal UX
export interface AgentInfo {
  name: string
  command: string
  available: boolean
  cwd: string
  description: string | null
  can_continue: boolean
  can_list_sessions: boolean
}

export interface AgentHistoryEntry {
  agent: string
  id: string
  title: string
  time: number | string | null
}

export interface AgentSessionInfo {
  id: string
  agent: string
  command: string
  cwd: string
  created_at: number
  running: boolean
  exited: boolean
  exit_code: number | null
  cols: number | null
  rows: number | null
  clients: number
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
  connected: boolean
  nats_url: string | null
  mdns_enabled: boolean
  peer_count: number
  peers: string[]
}


