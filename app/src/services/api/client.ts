const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api"

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
