import { useEffect } from "react"
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query"
import { apiClient } from "./client"
import type {
  DeploymentDetail,
  ServiceSummary,
  ServiceDetail,
  JobSummary,
  JobDetail,
  ProgramSummary,
  ProgramDetail,
  GitStatus,
  GraphModel,
  GraphSuggestion,
  MeshDeployment,
  RepoSummary,
  ProgramSyncResponse,
  StatusResponse,
  GatewayInfo,
  GatewayConfigRequest,
  ServiceActionResponse,
  SSEHealthEvent,
  MeshStatus,
  NodeSummary,
  NodeDetail,
  AgentInfo,
  AgentSessionInfo,
  AgentHistoryEntry,
} from "@/types"

// Compat hook for the /deployments/{name} unified detail endpoint
export function useDeployment(name: string) {
  return useQuery({
    queryKey: ["deployments", name],
    queryFn: () => apiClient.get<DeploymentDetail>(`/deployments/${name}`),
    enabled: !!name,
  })
}

export function useServices() {
  return useQuery({
    queryKey: ["services"],
    queryFn: () => apiClient.get<ServiceSummary[]>("/services"),
  })
}

export function useService(name: string) {
  return useQuery({
    queryKey: ["services", name],
    queryFn: () => apiClient.get<ServiceDetail>(`/services/${name}`),
    enabled: !!name,
  })
}

export function useJobs() {
  return useQuery({
    queryKey: ["jobs"],
    queryFn: () => apiClient.get<JobSummary[]>("/jobs"),
  })
}

// The stacks castle has handlers for — authoritative source for the program
// stack select, so a new backend stack appears without a frontend change.
export function useStacks() {
  return useQuery({
    queryKey: ["stacks"],
    queryFn: () => apiClient.get<string[]>("/stacks"),
    staleTime: Infinity,
  })
}

export function useJob(name: string) {
  return useQuery({
    queryKey: ["jobs", name],
    queryFn: () => apiClient.get<JobDetail>(`/jobs/${name}`),
    enabled: !!name,
  })
}

export function usePrograms(kind?: string) {
  const params = kind ? `?kind=${kind}` : ""
  return useQuery({
    queryKey: ["programs", kind ?? "all"],
    queryFn: () => apiClient.get<ProgramSummary[]>(`/programs${params}`),
  })
}

export function useProgram(name: string) {
  return useQuery({
    queryKey: ["programs", name],
    queryFn: () => apiClient.get<ProgramDetail>(`/programs/${name}`),
    enabled: !!name,
  })
}

export function useStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: () => apiClient.get<StatusResponse>("/status"),
    // SSE provides live updates; this is the fallback poll
    refetchInterval: 30_000,
  })
}

export function useGateway() {
  return useQuery({
    queryKey: ["gateway"],
    queryFn: () => apiClient.get<GatewayInfo>("/gateway"),
  })
}

export function useCaddyfile(enabled = true) {
  return useQuery({
    queryKey: ["gateway", "caddyfile"],
    queryFn: () => apiClient.get<{ content: string }>("/gateway/caddyfile"),
    enabled,
  })
}

async function waitForApi(attempts = 20, interval = 1000): Promise<void> {
  for (let i = 0; i < attempts; i++) {
    try {
      await apiClient.get<{ status: string }>("/health")
      return
    } catch {
      await new Promise((r) => setTimeout(r, interval))
    }
  }
}

export function useSystemdUnit(name: string, enabled = true) {
  return useQuery({
    queryKey: ["services", name, "unit"],
    queryFn: () => apiClient.get<{ service: string; timer: string | null }>(`/services/${name}/unit`),
    enabled: enabled && !!name,
  })
}

export function useServiceAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ name, action }: { name: string; action: string }) => {
      try {
        return await apiClient.post<ServiceActionResponse>(`/services/${name}/${action}`)
      } catch (err) {
        // Network error from self-restart killing the connection — expected
        if (err instanceof TypeError) {
          return { program: name, action, status: "accepted" } as ServiceActionResponse
        }
        throw err
      }
    },
    onSuccess: async (data) => {
      if (data.status === "accepted") {
        // API is restarting itself — poll until it's back, then refresh everything
        await waitForApi()
        qc.invalidateQueries()
      }
    },
  })
}

export interface ApplyResult {
  status: string
  planned: boolean
  changed: boolean
  activated: string[]
  restarted: string[]
  deactivated: string[]
  unchanged: string[]
  messages: string[]
}

// Converge the running system to config. Pass a name to converge one deployment,
// or plan:true for a dry-run diff. Handles the API restarting itself mid-apply.
export function useApply() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ name, plan }: { name?: string; plan?: boolean } = {}) => {
      try {
        return await apiClient.post<ApplyResult>("/apply", { name, plan })
      } catch (err) {
        if (err instanceof TypeError) {
          // Self-restart killed the connection — treat as accepted, wait + refresh.
          await waitForApi()
          return {
            status: "ok", planned: false, changed: true,
            activated: [], restarted: name ? [name] : [], deactivated: [],
            unchanged: [], messages: [],
          } as ApplyResult
        }
        throw err
      }
    },
    onSuccess: (data) => {
      if (!data.planned) qc.invalidateQueries()
    },
  })
}

// Set a deployment's desired on/off state, then converge it. One click = "make it
// so": edit config (declarative), then apply that single deployment.
export function useSetEnabled() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ name, enabled }: { name: string; enabled: boolean }) => {
      await apiClient.put(`/config/deployments/${name}/enabled`, { enabled })
      try {
        return await apiClient.post<ApplyResult>("/apply", { name })
      } catch (err) {
        if (err instanceof TypeError) {
          await waitForApi()
          return null
        }
        throw err
      }
    },
    onSuccess: () => qc.invalidateQueries(),
  })
}

// Deployment kind → the kind-scoped config section it writes to. Mirrors
// ConfigPanel's writeSection so a mutation can't hit a same-named twin.
const REACH_SECTION: Record<string, string> = {
  service: "services",
  job: "jobs",
  tool: "tools",
  static: "static",
  reference: "references",
}

// Create/update an external resource — a `reference` deployment (manager: none)
// that points at an endpoint castle doesn't run (a SaaS API, a remote service).
// Behind the System Map's "add external resource" authoring. No apply needed —
// a reference has no runtime unit; it just declares the endpoint.
export function useSaveReference() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      name,
      base_url,
      description,
    }: {
      name: string
      base_url: string
      description?: string
    }) => {
      await apiClient.put(`/config/references/${name}`, {
        config: { manager: "none", base_url, description: description || null },
      })
    },
    onSuccess: () => qc.invalidateQueries(),
  })
}

// Set a deployment's exposure (off | internal | public), then converge it. This
// is the mutation behind the System Map's drag-to-expose / drag-to-internet: a
// partial config merge (reach only, other fields preserved) followed by apply.
export function useSetReach() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      name,
      kind,
      reach,
    }: {
      name: string
      kind: string
      reach: "off" | "internal" | "public"
    }) => {
      const section = REACH_SECTION[kind] ?? "services"
      await apiClient.put(`/config/${section}/${name}`, { config: { reach } })
      try {
        return await apiClient.post<ApplyResult>("/apply", { name })
      } catch (err) {
        if (err instanceof TypeError) {
          await waitForApi()
          return null
        }
        throw err
      }
    },
    onSuccess: () => qc.invalidateQueries(),
  })
}

// Delete a deployment from castle.yaml (the kind-scoped removal; keeps the
// program). Behind the System Map's node deletion.
export function useDeleteDeployment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ name, kind }: { name: string; kind: string }) => {
      const section = REACH_SECTION[kind] ?? "services"
      await apiClient.delete(`/config/${section}/${name}`)
    },
    onSuccess: () => qc.invalidateQueries(),
  })
}

interface Requirement {
  kind: string // system | deployment
  ref: string
  bind?: string | null
}

// Add or remove a `requires` edge on a deployment, then converge. Reads the
// deployment's authoritative current requires (so system deps and binds are
// preserved), applies the single add/remove, writes it back, and applies. Behind
// the System Map's draw-a-line / delete-a-line dependency editing.
export function useMutateRequires() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      name,
      kind,
      add,
      remove,
    }: {
      name: string
      kind: string
      add?: string
      remove?: string
    }) => {
      const section = REACH_SECTION[kind] ?? "services"
      const detail = await apiClient.get<DeploymentDetail>(`/deployments/${name}`)
      const cur = (detail.manifest?.requires as Requirement[] | undefined) ?? []
      let next = cur
      if (remove) next = next.filter((r) => !(r.kind === "deployment" && r.ref === remove))
      if (add && !next.some((r) => r.kind === "deployment" && r.ref === add))
        next = [...next, { kind: "deployment", ref: add }]
      await apiClient.put(`/config/${section}/${name}`, {
        config: { requires: next.length ? next : null },
      })
      try {
        return await apiClient.post<ApplyResult>("/apply", { name })
      } catch (err) {
        if (err instanceof TypeError) {
          await waitForApi()
          return null
        }
        throw err
      }
    },
    onSuccess: () => qc.invalidateQueries(),
  })
}

export function useProgramAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, action }: { name: string; action: string }) =>
      apiClient.post<{ program: string; action: string; status: string; output: string }>(
        `/programs/${name}/${action}`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["programs"] })
    },
  })
}

// Git status of a program's working copy. The backend fetches from the remote,
// so this call is comparatively slow — hence its own query (not part of the
// program detail) with a short staleTime. `enabled` lets the caller skip it for
// programs with no repo.
export function useProgramGit(name: string, enabled = true) {
  return useQuery({
    queryKey: ["programs", name, "git"],
    queryFn: () => apiClient.get<GitStatus>(`/programs/${name}/git`),
    enabled: enabled && !!name,
    staleTime: 30_000,
  })
}

// Fast-forward a program's source (git pull). Pull-only — converge (restart/apply)
// stays a separate, explicit step. Refreshes the program and its git status.
export function useProgramSync() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      apiClient.post<ProgramSyncResponse>(`/programs/${name}/sync`),
    onSuccess: (_data, name) => {
      qc.invalidateQueries({ queryKey: ["programs", name, "git"] })
      qc.invalidateQueries({ queryKey: ["programs"] })
    },
  })
}

// Server-side directory browser for the "Add program" flow. Programs live on the
// server's filesystem, so the picker browses the server's dirs (the browser's own
// file dialog only sees the client machine). `path` null => the repos dir.
export interface BrowseEntry {
  name: string
  path: string
  is_program: boolean
  is_git: boolean
}
export interface BrowseResult {
  path: string
  parent: string | null
  repos_dir: string
  entries: BrowseEntry[]
}
export function useBrowse(path: string | null, enabled = true) {
  return useQuery({
    queryKey: ["browse", path ?? "@repos"],
    queryFn: () =>
      apiClient.get<BrowseResult>(
        `/fs/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`,
      ),
    enabled,
  })
}

export interface AdoptResult {
  ok: boolean
  program: string
  source: string
  stack: string | null
  repo: string | null
  commands: string[]
  is_git_url: boolean
}
// Adopt an existing repo as a program (the web `castle program add`). Refreshes
// the catalog + the derived graph/repo views.
export function useAdoptProgram() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { target: string; name?: string; description?: string }) =>
      apiClient.post<AdoptResult>("/programs/adopt", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["programs"] })
      qc.invalidateQueries({ queryKey: ["graph"] })
      qc.invalidateQueries({ queryKey: ["repos"] })
    },
  })
}

export function useRepos() {
  return useQuery({
    queryKey: ["repos"],
    queryFn: () => apiClient.get<RepoSummary[]>("/repos"),
    staleTime: 30_000,
  })
}

// Fast-forward a whole repo (git pull the working copy). Pull-only — converge is
// separate. Refreshes repos, programs, and their git status.
export function useRepoSync() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (key: string) =>
      apiClient.post<ProgramSyncResponse>(`/repos/${key}/sync`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["repos"] })
      qc.invalidateQueries({ queryKey: ["programs"] })
      qc.invalidateQueries({ queryKey: ["graph"] })
    },
  })
}

// The derived relationship model (repos, requires edges, functional/fresh status).
// Fetches git status per repo server-side, so it's comparatively slow — its own
// query with a modest staleTime.
export function useGraph() {
  return useQuery({
    queryKey: ["graph"],
    queryFn: () => apiClient.get<GraphModel>("/graph"),
    staleTime: 30_000,
  })
}

// Undeclared-consumption suggestions (env → provider socket matches). Advisory only.
export function useSuggestions() {
  return useQuery({
    queryKey: ["graph", "suggestions"],
    queryFn: () => apiClient.get<{ suggestions: GraphSuggestion[] }>("/graph/suggestions"),
    staleTime: 30_000,
  })
}

// Deployments on other (mesh-discovered) castle nodes, for the multi-node map.
export function useMeshDeployments() {
  return useQuery({
    queryKey: ["mesh", "deployments"],
    queryFn: () => apiClient.get<{ deployments: MeshDeployment[] }>("/mesh/deployments"),
    refetchInterval: 30_000,
  })
}

export function useSaveGatewayConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: GatewayConfigRequest) =>
      apiClient.put<{ status: string; message: string }>("/gateway/config", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["gateway"] })
    },
  })
}

export function useNodes() {
  return useQuery({
    queryKey: ["nodes"],
    queryFn: () => apiClient.get<NodeSummary[]>("/nodes"),
  })
}

export function useNode(hostname: string) {
  return useQuery({
    queryKey: ["nodes", hostname],
    queryFn: () => apiClient.get<NodeDetail>(`/nodes/${hostname}`),
    enabled: !!hostname,
  })
}

export function useMeshStatus() {
  return useQuery({
    queryKey: ["mesh"],
    queryFn: () => apiClient.get<MeshStatus>("/mesh/status"),
    refetchInterval: 30_000,
  })
}

export function useAgents() {
  return useQuery({
    queryKey: ["agents"],
    queryFn: () => apiClient.get<AgentInfo[]>("/agents"),
    staleTime: Infinity,
  })
}

export function useAgentSessions() {
  return useQuery({
    queryKey: ["agent-sessions"],
    queryFn: () => apiClient.get<AgentSessionInfo[]>("/agents/sessions"),
    refetchInterval: 5_000,
  })
}

export function useAgentHistory(enabled: boolean) {
  return useQuery({
    queryKey: ["agent-history"],
    queryFn: () => apiClient.get<AgentHistoryEntry[]>("/agents/history"),
    enabled,
    staleTime: 10_000,
  })
}

export function useDeleteAgentSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiClient.delete(`/agents/sessions/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agent-sessions"] }),
  })
}

export function useEventStream() {
  const qc = useQueryClient()

  useEffect(() => {
    const url = apiClient.streamUrl("/stream")
    const es = new EventSource(url)

    es.addEventListener("health", (e) => {
      const data: SSEHealthEvent = JSON.parse(e.data)
      qc.setQueryData<StatusResponse>(["status"], { statuses: data.statuses })
    })

    es.addEventListener("service-action", () => {
      // Health event already pushes correct status; just refetch services/jobs
      // in case the action changed what's available
      qc.invalidateQueries({ queryKey: ["services"] })
      qc.invalidateQueries({ queryKey: ["jobs"] })
    })

    es.addEventListener("program-sync", () => {
      // A program's source was pulled (possibly by another client) — refresh
      // programs and their git status.
      qc.invalidateQueries({ queryKey: ["programs"] })
    })

    es.addEventListener("mesh", () => {
      // A remote node updated or went offline — refresh mesh, nodes, and gateway
      qc.invalidateQueries({ queryKey: ["mesh"] })
      qc.invalidateQueries({ queryKey: ["nodes"] })
      qc.invalidateQueries({ queryKey: ["gateway"] })
    })

    es.onerror = () => {
      // EventSource auto-reconnects; nothing to do
    }

    return () => es.close()
  }, [qc])
}

// --- Secrets ---

export interface SecretsInfo {
  backend: string
  addr: string | null
  role: string
  writable: boolean
}

export function useSecretsInfo() {
  return useQuery({
    queryKey: ["secrets-info"],
    queryFn: () => apiClient.get<SecretsInfo>("/secrets/info"),
  })
}

export function useSecrets() {
  return useQuery({
    queryKey: ["secrets"],
    queryFn: () => apiClient.get<string[]>("/secrets"),
  })
}

export function useSetSecret() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, value }: { name: string; value: string }) =>
      apiClient.put(`/secrets/${name}`, { value }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["secrets"] }),
  })
}

export function useDeleteSecret() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => apiClient.delete(`/secrets/${name}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["secrets"] }),
  })
}

export function useSecretOverrides() {
  return useQuery({
    queryKey: ["secret-overrides"],
    queryFn: () =>
      apiClient.get<{ overrides: Record<string, string[]> }>("/secrets/overrides"),
  })
}

export function useSetOverride() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ node, name, value }: { node: string; name: string; value: string }) =>
      apiClient.put(`/secrets/overrides/${node}/${name}`, { value }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["secret-overrides"] }),
  })
}

export function useDeleteOverride() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ node, name }: { node: string; name: string }) =>
      apiClient.delete(`/secrets/overrides/${node}/${name}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["secret-overrides"] }),
  })
}
