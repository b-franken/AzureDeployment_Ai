export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/+$/, "")
export const REQUEST_TIMEOUT_MS = 30000

export class ApiError extends Error {
  constructor(
    message: string,
    public cause?: unknown,
    public status?: number,
    public details?: unknown
  ) {
    super(message)
    this.name = "ApiError"
  }
}

export type ChatMsg = { role: "user" | "assistant" | "system"; content: string }
type JSONObject = Record<string, unknown>

class APIClient {
  private baseURL: string
  private maxRetries: number
  private retryDelay: number
  private timeoutMs: number

  constructor(baseURL: string, opts?: { maxRetries?: number; retryDelay?: number; timeoutMs?: number }) {
    this.baseURL = baseURL.replace(/\/+$/, "")
    this.maxRetries = opts?.maxRetries ?? 3
    this.retryDelay = opts?.retryDelay ?? 1000
    this.timeoutMs = opts?.timeoutMs ?? REQUEST_TIMEOUT_MS
  }

  private isRetryableStatus(status?: number) {
    return !!status && [408, 429, 500, 502, 503, 504].includes(status)
  }

  private isNetworkError(err: unknown) {
    if (err instanceof ApiError) return false
    if (err instanceof Error && (err.name === "AbortError" || err.name === "TypeError")) return true
    return false
  }

  private parseRetryAfter(header: string | null): number | null {
    if (!header) return null
    const s = Number(header)
    if (!Number.isNaN(s)) return Math.max(0, s) * 1000
    const date = new Date(header).getTime()
    if (Number.isNaN(date)) return null
    const ms = date - Date.now()
    return ms > 0 ? ms : null
  }

  private nextDelay(attempt: number, retryAfterMs?: number | null) {
    if (retryAfterMs && retryAfterMs > 0) return retryAfterMs
    const base = this.retryDelay * Math.pow(2, attempt)
    const jitter = Math.floor(Math.random() * 250)
    return base + jitter
  }

  private withTimeout(init?: RequestInit, timeout?: number) {
    const controller = new AbortController()
    const id = setTimeout(() => controller.abort(), timeout ?? this.timeoutMs)
    const merged: RequestInit = { ...init, signal: controller.signal }
    return { merged, clear: () => clearTimeout(id) }
  }

  async request<T>(
    path: string,
    init: RequestInit & { timeoutMs?: number; context?: string } = {},
    attempt = 0
  ): Promise<T> {
    const url = `${this.baseURL}${path.startsWith("/") ? "" : "/"}${path}`
    const headers: HeadersInit = { "Content-Type": "application/json", ...(init.headers || {}) }
    const { merged, clear } = this.withTimeout({ ...init, headers }, init.timeoutMs)
    try {
      const res = await fetch(url, merged)
      if (!res.ok) {
        let detail: JSONObject | string | null = null
        try {
          const ct = res.headers.get("content-type") || ""
          if (ct.includes("application/json")) detail = await res.clone().json()
          else detail = await res.clone().text()
        } catch { }
        const messageFromBody =
          typeof detail === "string"
            ? detail
            : typeof detail === "object" && detail
              ? String((detail as any).detail) || String((detail as any).message) || JSON.stringify(detail)
              : ""
        const message = messageFromBody || `${init.context || "request"} failed ${res.status}`
        const err = new ApiError(message, undefined, res.status, detail)
        if (attempt < this.maxRetries && this.isRetryableStatus(res.status)) {
          const retryAfter = this.parseRetryAfter(res.headers.get("retry-after"))
          await this.delay(this.nextDelay(attempt, retryAfter))
          return this.request<T>(path, init, attempt + 1)
        }
        throw err
      }
      if (res.status === 204) return undefined as unknown as T
      const ct = res.headers.get("content-type") || ""
      if (ct.includes("application/json")) return (await res.json()) as T
      return (await res.text()) as unknown as T
    } catch (e) {
      if (e instanceof ApiError) {
        if (attempt < this.maxRetries && this.isRetryableStatus(e.status)) {
          await this.delay(this.nextDelay(attempt))
          return this.request<T>(path, init, attempt + 1)
        }
        throw e
      }
      const isTimeout = e instanceof Error && e.name === "AbortError"
      const wrapped = new ApiError(isTimeout ? `${init.context || "request"} timed out` : `${init.context || "request"} error`, e)
      if (attempt < this.maxRetries && (isTimeout || this.isNetworkError(e))) {
        await this.delay(this.nextDelay(attempt))
        return this.request<T>(path, init, attempt + 1)
      }
      throw wrapped
    } finally {
      clear()
    }
  }

  private delay(ms: number) {
    return new Promise((r) => setTimeout(r, ms))
  }

  get<T>(path: string, init?: RequestInit & { timeoutMs?: number; context?: string }) {
    return this.request<T>(path, { method: "GET", ...(init || {}) })
  }

  post<T>(path: string, body?: unknown, init?: RequestInit & { timeoutMs?: number; context?: string }) {
    const payload = body === undefined ? undefined : JSON.stringify(body)
    return this.request<T>(path, { method: "POST", body: payload, ...(init || {}) })
  }
}

export const apiClient = new APIClient(API_BASE_URL)

export type AuthResult = {
  access_token: string
  token_type: "bearer"
  expires_in: number
  user: { id: string; email: string; roles: string[] }
}

export type ChatV2Response = {
  response: string
  correlation_id: string
  processing_time: number
}

export type ChatRequest = {
  input: string
  memory?: ChatMsg[]
  provider?: string | null
  model?: string | null
  enable_tools?: boolean
  preferred_tool?: string | null
  allowlist?: string[] | null
  dry_run?: boolean
  subscription_id?: string | null
  resource_group?: string | null
  environment?: string
}

export type ReviewRequest = {
  user_input: string
  assistant_reply: string
  provider?: string | null
  model?: string | null
}

export type DeployRequestItem = {
  id: string | number
  status: "pending" | "approved" | "rejected" | "deployed" | "failed"
  request: string
  environment: string
  cost_estimate?: number | null
  created_at: string
  updated_at: string
}

export function splitModel(id: string): { provider: string | null; model: string | null } {
  if (!id) return { provider: null, model: null }
  const i = id.indexOf(":")
  if (i === -1) return { provider: null, model: id }
  return { provider: id.slice(0, i), model: id.slice(i + 1) }
}

export async function chat(
  input: string,
  memory?: ChatMsg[] | null,
  providerOrOpts?: string | null | {
    provider?: string | null
    model?: string | null
    enable_tools?: boolean
    preferred_tool?: string | null
    allowlist?: string[] | null
    dry_run?: boolean
    subscription_id?: string | null
    resource_group?: string | null
    environment?: string
  },
  model?: string | null,
  enable_tools?: boolean,
  preferred_tool?: string | null,
  allowlist?: string[] | null
): Promise<string> {
  const isOpts = providerOrOpts && typeof providerOrOpts === "object" && !Array.isArray(providerOrOpts)
  const provider = isOpts ? providerOrOpts.provider ?? null : (providerOrOpts as string | null) ?? null
  const mdl = isOpts ? providerOrOpts.model ?? null : model ?? null
  const tools = isOpts ? !!providerOrOpts.enable_tools : !!enable_tools
  const pref = isOpts ? providerOrOpts.preferred_tool ?? null : preferred_tool ?? null
  const allow = isOpts ? providerOrOpts.allowlist ?? [] : allowlist ?? []
  const dry = isOpts ? providerOrOpts.dry_run : undefined
  const sub = isOpts ? providerOrOpts.subscription_id : undefined
  const rg = isOpts ? providerOrOpts.resource_group : undefined
  const env = isOpts ? providerOrOpts.environment : undefined
  const data = await apiClient.post<{ output: string }>(
    "/api/chat?stream=false",
    {
      input,
      memory: memory ?? [],
      provider,
      model: mdl,
      enable_tools: tools,
      preferred_tool: pref,
      allowlist: allow,
      dry_run: dry,
      subscription_id: sub,
      resource_group: rg,
      environment: env,
    },
    { context: "chat" }
  )
  if (!data || typeof data.output !== "string") throw new ApiError("chat response malformed")
  return data.output
}

export async function chatV2(
  token: string | null,
  body: {
    input: string
    memory?: ChatMsg[]
    provider?: string | null
    model?: string | null
    enable_tools?: boolean
    correlation_id?: string
    dry_run?: boolean
    subscription_id?: string | null
    resource_group?: string | null
    environment?: string
  }
): Promise<ChatV2Response> {
  const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {}
  return apiClient.post<ChatV2Response>("/api/chat/v2", body, { headers, context: "chat-v2" })
}

export async function review_once(
  user_input: string,
  assistant_reply: string,
  opts?: { provider?: string | null; model?: string | null }
): Promise<string> {
  const data = await apiClient.post<{ output: string }>(
    "/api/review",
    { user_input, assistant_reply, provider: opts?.provider, model: opts?.model },
    { context: "review" }
  )
  if (!data || typeof data.output !== "string") throw new ApiError("review response malformed")
  return data.output
}

export async function apiHealthz(): Promise<{ status: string }> {
  return apiClient.get("/api/health", { context: "health" })
}

export async function apiStatus(): Promise<any> {
  return apiClient.get("/api/status", { context: "status" })
}

export type LoginResult = {
  access_token: string
  token_type: "bearer"
  expires_in: number
  user: { id: string; email: string; roles: string[] }
}

export async function login(email: string, password: string): Promise<LoginResult> {
  return { access_token: "dev-token", token_type: "bearer", expires_in: 3600, user: { id: "dev", email, roles: ["user"] } }
}

export async function logout(): Promise<{ message: string }> {
  return { message: "ok" }
}

export async function refresh(token: string): Promise<{ access_token: string; expires_in: number }> {
  try {
    const headers: HeadersInit = { Authorization: `Bearer ${token}` }
    return await apiClient.post<{ access_token: string; expires_in: number }>("/api/auth/refresh", undefined, {
      headers,
      context: "auth/refresh",
    })
  } catch {
    return { access_token: "dev-token", expires_in: 3600 }
  }
}

export async function listDeployRequests(token: string): Promise<{ requests: DeployRequestItem[] } | DeployRequestItem[]> {
  const headers: HeadersInit = { Authorization: `Bearer ${token}` }
  return apiClient.get("/api/deploy/requests", { headers, context: "deploy/list" })
}

export async function createDeployRequest(
  token: string,
  request: Partial<DeployRequestItem> & { request?: string; environment?: string }
): Promise<DeployRequestItem> {
  const headers: HeadersInit = { Authorization: `Bearer ${token}` }
  return apiClient.post("/api/deploy/requests", request, { headers, context: "deploy/create" })
}

export async function approveDeployRequest(token: string, id: string): Promise<{ ok: true }> {
  const headers: HeadersInit = { Authorization: `Bearer ${token}` }
  return apiClient.post(`/api/deploy/requests/${encodeURIComponent(id)}/approve`, {}, { headers, context: "deploy/approve" })
}

export async function rejectDeployRequest(token: string, id: string): Promise<{ ok: true }> {
  const headers: HeadersInit = { Authorization: `Bearer ${token}` }
  return apiClient.post(`/api/deploy/requests/${encodeURIComponent(id)}/reject`, {}, { headers, context: "deploy/reject" })
}

export async function deployRequestById(token: string, id: string): Promise<{ ok: true }> {
  const headers: HeadersInit = { Authorization: `Bearer ${token}` }
  return apiClient.post(`/api/deploy/requests/${encodeURIComponent(id)}/deploy`, {}, { headers, context: "deploy/deploy" })
}
