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
