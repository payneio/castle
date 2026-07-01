// Resolve the castle-api base URL. The gateway serves each service at its own
// subdomain (<name>.<domain>), so when the dashboard runs at castle.<domain>
// the API lives at castle-api.<domain> — a cross-origin call (castle-api allows
// CORS *). When served at a bare host (dev, or the off-mode :9000 gateway), the
// API is reachable same-origin at /api.
function resolveApiBase(): string {
  const configured = import.meta.env.VITE_API_BASE_URL
  if (configured) return configured
  if (typeof window !== "undefined") {
    const { protocol, hostname } = window.location
    const labels = hostname.split(".")
    if (labels.length > 2) {
      return `${protocol}//castle-api.${labels.slice(1).join(".")}`
    }
  }
  return "/api"
}

const BASE_URL = resolveApiBase()

class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

class ApiClient {
  private baseUrl: string

  constructor(baseUrl = BASE_URL) {
    this.baseUrl = baseUrl
  }

  async get<T>(path: string): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`)
    if (!resp.ok) {
      throw new ApiError(resp.status, await resp.text())
    }
    return resp.json()
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!resp.ok) {
      throw new ApiError(resp.status, await resp.text())
    }
    return resp.json()
  }

  async put<T>(path: string, body?: unknown): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method: "PUT",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!resp.ok) {
      throw new ApiError(resp.status, await resp.text())
    }
    return resp.json()
  }

  async delete<T>(path: string): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`, { method: "DELETE" })
    if (!resp.ok) {
      throw new ApiError(resp.status, await resp.text())
    }
    return resp.json()
  }

  streamUrl(path: string): string {
    return `${this.baseUrl}${path}`
  }
}

export const apiClient = new ApiClient()
export { ApiError }
