import { useEffect } from "react"
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query"
import { apiClient } from "./client"
import type {
  ComponentDetail,
  ServiceSummary,
  ServiceDetail,
  JobSummary,
  JobDetail,
  ProgramSummary,
  ProgramDetail,
  StatusResponse,
  GatewayInfo,
  ServiceActionResponse,
  SSEHealthEvent,
  MeshStatus,
  NodeSummary,
  NodeDetail,
  ToolSummary,
  ToolDetail,
} from "@/types"

// Legacy compat hook — used by ConfigEditorPage and ComponentRedirect
export function useComponent(name: string) {
  return useQuery({
    queryKey: ["components", name],
    queryFn: () => apiClient.get<ComponentDetail>(`/components/${name}`),
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

export function useJob(name: string) {
  return useQuery({
    queryKey: ["jobs", name],
    queryFn: () => apiClient.get<JobDetail>(`/jobs/${name}`),
    enabled: !!name,
  })
}

export function usePrograms() {
  return useQuery({
    queryKey: ["programs"],
    queryFn: () => apiClient.get<ProgramSummary[]>("/programs"),
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
          return { component: name, action, status: "accepted" } as ServiceActionResponse
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

export function useProgramAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, action }: { name: string; action: string }) =>
      apiClient.post<{ component: string; action: string; status: string; output: string }>(
        `/programs/${name}/${action}`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["programs"] })
    },
  })
}

export function useGatewayReload() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiClient.post<{ status: string }>("/gateway/reload"),
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

export function useTools() {
  return useQuery({
    queryKey: ["tools"],
    queryFn: () => apiClient.get<ToolSummary[]>("/tools"),
  })
}

export function useToolDetail(name: string) {
  return useQuery({
    queryKey: ["tools", name],
    queryFn: () => apiClient.get<ToolDetail>(`/tools/${name}`),
    enabled: !!name,
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
