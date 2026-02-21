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

export function useServiceAction() {
  return useMutation({
    mutationFn: ({ name, action }: { name: string; action: string }) =>
      apiClient.post<ServiceActionResponse>(`/services/${name}/${action}`),
    // SSE health event handles the UI update; no need to refetch here
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
