const base =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"

export type ChatMsg = {
    role: "user" | "assistant" | "system"
    content: string
}

type HeadersDict = { [k: string]: string }

function withAuth(token?: string): HeadersDict {
    return token ? { Authorization: `Bearer ${token}` } : {}
}

export function splitModel(
    id: string
): { provider: string | null; model: string | null } {
    if (!id) return { provider: null, model: null }
    const i = id.indexOf(":")
    if (i === -1) return { provider: null, model: id }
    return { provider: id.slice(0, i), model: id.slice(i + 1) }
}

export type AuthResult = {
    access_token: string
    token_type: "bearer"
    expires_in: number
    user: { id: string; email: string; roles: string[] }
}

export async function login(
    email: string,
    password: string
): Promise<AuthResult> {
    const res = await fetch(`${base}/api/v2/auth/login`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password }),
    })
    if (!res.ok) throw new Error(`login failed ${res.status}`)
    return res.json()
}

export async function logout(token: string): Promise<void> {
    const res = await fetch(`${base}/api/v2/auth/logout`, {
        method: "POST",
        headers: { "content-type": "application/json", ...withAuth(token) },
    })
    if (!res.ok) throw new Error(`logout failed ${res.status}`)
}

export type ChatV2Response = {
    response: string
    correlation_id: string
    processing_time: number
}

export async function chatV2(
    token: string,
    args: {
        input: string
        memory?: ChatMsg[]
        provider?: string | null
        model?: string | null
        enable_tools?: boolean
    }
): Promise<ChatV2Response> {
    const res = await fetch(`${base}/api/v2/chat/chat`, {
        method: "POST",
        headers: { "content-type": "application/json", ...withAuth(token) },
        body: JSON.stringify({
            input: args.input,
            memory: args.memory ?? [],
            provider: args.provider ?? null,
            model: args.model ?? null,
            enable_tools: !!args.enable_tools,
        }),
    })
    if (!res.ok) throw new Error(`chatV2 failed ${res.status}`)
    return res.json()
}

export async function chat(
    message: string,
    history: ChatMsg[],
    opts?: {
        provider?: string | null
        model?: string | null
        enable_tools?: boolean
        preferred_tool?: string | null
        allowlist?: string[] | null
    }
): Promise<string> {
    const body = {
        input: message,
        memory: history,
        provider: opts?.provider ?? null,
        model: opts?.model ?? null,
        enable_tools: !!opts?.enable_tools,
        preferred_tool: opts?.preferred_tool ?? null,
        allowlist: opts?.allowlist ?? [],
    }
    const res = await fetch(`${base}/api/chat`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
    })
    if (!res.ok) throw new Error(`chat failed ${res.status}`)
    const data = await res.json()
    return String(data?.output ?? "")
}

export async function review_once(
    user: string,
    assistant: string,
    opts?: { provider?: string | null; model?: string | null }
): Promise<string> {
    const res = await fetch(`${base}/api/review`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
            user_input: user,
            assistant_reply: assistant,
            provider: opts?.provider ?? null,
            model: opts?.model ?? null,
        }),
    })
    if (!res.ok) throw new Error(`review failed ${res.status}`)
    const data = await res.json()
    return String(data?.output ?? "")
}

export type DeployRequest = {
    request: string
    subscription_id: string
    resource_group?: string | null
    environment?: "development" | "staging" | "production"
    dry_run?: boolean
    cost_limit?: number | null
    tags?: Record<string, string>
}

export async function deploy(
    token: string,
    body: DeployRequest
) {
    const res = await fetch(`${base}/api/v2/deploy/deploy`, {
        method: "POST",
        headers: { "content-type": "application/json", ...withAuth(token) },
        body: JSON.stringify({
            request: body.request,
            subscription_id: body.subscription_id,
            resource_group: body.resource_group ?? null,
            environment: body.environment ?? "development",
            dry_run: body.dry_run ?? true,
            cost_limit: body.cost_limit ?? null,
            tags: body.tags ?? {},
        }),
    })
    if (!res.ok) throw new Error(`deploy failed ${res.status}`)
    return res.json()
}

export type CostAnalysisArgs = {
    subscription_id: string
    start_date: string
    end_date: string
    group_by?: string[] | null
    include_forecast?: boolean
    include_recommendations?: boolean
}

export async function analyzeCosts(
    token: string,
    args: CostAnalysisArgs
) {
    const res = await fetch(`${base}/api/v2/cost/cost/analysis`, {
        method: "POST",
        headers: { "content-type": "application/json", ...withAuth(token) },
        body: JSON.stringify({
            subscription_id: args.subscription_id,
            start_date: args.start_date,
            end_date: args.end_date,
            group_by: args.group_by ?? null,
            include_forecast: !!args.include_forecast,
            include_recommendations: !!args.include_recommendations,
        }),
    })
    if (!res.ok) throw new Error(`cost analysis failed ${res.status}`)
    return res.json()
}

export async function auditLogs(
    token: string,
    params?: {
        start_date?: string
        end_date?: string
        user_id?: string
        page?: number
        page_size?: number
    }
) {
    const q = new URLSearchParams()
    if (params?.start_date) q.set("start_date", params.start_date)
    if (params?.end_date) q.set("end_date", params.end_date)
    if (params?.user_id) q.set("user_id", params.user_id)
    if (params?.page) q.set("page", String(params.page))
    if (params?.page_size) q.set("page_size", String(params.page_size))
    const res = await fetch(
        `${base}/api/v2/audit/audit/logs?${q.toString()}`,
        { headers: { ...withAuth(token) } }
    )
    if (!res.ok) throw new Error(`audit logs failed ${res.status}`)
    return res.json()
}

export async function metrics(token: string) {
    const res = await fetch(`${base}/api/v2/metrics`, {
        headers: { ...withAuth(token) },
    })
    if (!res.ok) throw new Error(`metrics failed ${res.status}`)
    return res.json()
}

export async function apiHealthz(): Promise<{ status: string }> {
    const res = await fetch(`${base}/healthz`)
    if (!res.ok) throw new Error(`healthz failed ${res.status}`)
    return res.json()
}

export async function apiStatus(): Promise<any> {
    const res = await fetch(`${base}/api/v2/status`)
    if (!res.ok) throw new Error(`status failed ${res.status}`)
    return res.json()
}
