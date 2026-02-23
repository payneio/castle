import { useEffect } from "react"
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query"
import { apiClient } from "./client"
import type {
  ComponentSummary,
  ComponentDetail,
  StatusResponse,
  GatewayInfo,
  ServiceActionResponse,
  SSEHealthEvent,
  ToolSummary,
  ToolDetail,
} from "@/types"

export function useComponents() {
  return useQuery({
    queryKey: ["components"],
    queryFn: () => apiClient.get<ComponentSummary[]>("/components"),
  })
}

export function useComponent(name: string) {
  return useQuery({
    queryKey: ["components", name],
    queryFn: () => apiClient.get<ComponentDetail>(`/components/${name}`),
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

export function useToolAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, action }: { name: string; action: "install" | "uninstall" }) =>
      apiClient.post<{ component: string; action: string; status: string }>(
        `/tools/${name}/${action}`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["components"] })
    },
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
      // Health event already pushes correct status; just refetch components
      // in case the action changed what's available
      qc.invalidateQueries({ queryKey: ["components"] })
    })

    es.onerror = () => {
      // EventSource auto-reconnects; nothing to do
    }

    return () => es.close()
  }, [qc])
}
