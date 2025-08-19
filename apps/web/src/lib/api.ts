const base =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const REQUEST_TIMEOUT_MS = 15000;

export class ApiError extends Error {
  constructor(message: string, public cause?: unknown, public status?: number) {
    super(message);
    this.name = "ApiError";
  }
}

async function fetchWithTimeout(
  url: string,
  options: RequestInit,
  context: string,
  timeout = REQUEST_TIMEOUT_MS
) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    if (!res.ok) {
      let detail = `${context} failed ${res.status}`;
      try {
        const body = await res.clone().json();
        if (typeof body?.detail === "string") detail = body.detail;
        if (typeof body?.message === "string") detail = body.message;
      } catch {
        // ignore body parse errors
      }
      throw new ApiError(detail, undefined, res.status);
    }
    return res;
  } catch (err: any) {
    if (err instanceof ApiError) throw err;
    if (err?.name === "AbortError") {
      throw new ApiError(`${context} timed out`, err);
    }
    throw new ApiError(`${context} error`, err);
  } finally {
    clearTimeout(id);
  }
}

export type ChatMsg = {
  role: "user" | "assistant" | "system";
  content: string;
};

type HeadersDict = { [k: string]: string };

function withAuth(token?: string): HeadersDict {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function splitModel(
  id: string
): { provider: string | null; model: string | null } {
  if (!id) return { provider: null, model: null };
  const i = id.indexOf(":");
  if (i === -1) return { provider: null, model: id };
  return { provider: id.slice(0, i), model: id.slice(i + 1) };
}

export type AuthResult = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: { id: string; email: string; roles: string[] };
};

export type RefreshResult = {
  access_token: string;
  token_type?: "bearer";
  expires_in?: number;
};

export async function login(email: string, password: string): Promise<AuthResult> {
  const res = await fetchWithTimeout(
    `${base}/api/auth/login`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password }),
    },
    "login"
  );
  return res.json();
}

export async function logout(token: string): Promise<void> {
  await fetchWithTimeout(
    `${base}/api/auth/logout`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...withAuth(token),
      },
    },
    "logout"
  );
}

export async function refresh(token: string): Promise<RefreshResult> {
  const res = await fetchWithTimeout(
    `${base}/api/auth/refresh`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...withAuth(token),
      },
    },
    "refresh"
  );
  return res.json();
}

export type ChatV2Response = {
  response: string;
  correlation_id: string;
  processing_time: number;
};

export async function chatV2(
  token: string,
  args: {
    input: string;
    memory?: ChatMsg[];
    provider?: string | null;
    model?: string | null;
    enable_tools?: boolean;
  }
): Promise<ChatV2Response> {
  const res = await fetchWithTimeout(
    `${base}/api/chat/v2`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...withAuth(token),
      },
      body: JSON.stringify({
        input: args.input,
        memory: args.memory ?? [],
        provider: args.provider ?? null,
        model: args.model ?? null,
        enable_tools: !!args.enable_tools,
      }),
    },
    "chatV2"
  );
  return res.json();
}

export async function chat(
  message: string,
  history: ChatMsg[],
  opts?: {
    provider?: string | null;
    model?: string | null;
    enable_tools?: boolean;
    preferred_tool?: string | null;
    allowlist?: string[] | null;
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
  };
  const res = await fetchWithTimeout(
    `${base}/api/chat`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    },
    "chat"
  );
  const data = await res.json();
  return String(data?.output ?? "");
}

export async function review_once(
  user: string,
  assistant: string,
  opts?: { provider?: string | null; model?: string | null }
): Promise<string> {
  const res = await fetchWithTimeout(
    `${base}/api/review`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        user_input: user,
        assistant_reply: assistant,
        provider: opts?.provider ?? null,
        model: opts?.model ?? null,
      }),
    },
    "review"
  );
  const data = await res.json();
  return String(data?.output ?? "");
}

export type DeployRequest = {
  request: string;
  subscription_id: string;
  resource_group?: string | null;
  environment?: "development" | "staging" | "production";
  dry_run?: boolean;
  cost_limit?: number | null;
  tags?: Record<string, string>;
};

// Orchestrated deploy, not the approval queue API
export async function deploy(token: string, body: DeployRequest) {
  const res = await fetchWithTimeout(
    `${base}/api/deploy`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...withAuth(token),
      },
      body: JSON.stringify({
        request: body.request,
        subscription_id: body.subscription_id,
        resource_group: body.resource_group ?? null,
        environment: body.environment ?? "development",
        dry_run: body.dry_run ?? true,
        cost_limit: body.cost_limit ?? null,
        tags: body.tags ?? {},
      }),
    },
    "deploy"
  );
  return res.json();
}

/**
 * Deployment Requests API (approval workflow)
 * Endpoints assumed:
 *  - GET    /api/deploy/requests
 *  - POST   /api/deploy/requests
 *  - POST   /api/deploy/requests/:id/approve
 *  - POST   /api/deploy/requests/:id/reject
 *  - POST   /api/deploy/requests/:id/deploy
 */
export type DeployRequestItem = {
  id: string | number;
  status: "pending" | "approved" | "rejected" | "deployed" | "failed";
  request: string;
  environment: string;
  cost_estimate?: number | null;
  created_at: string; // ISO
  updated_at: string; // ISO
};

export async function listDeployRequests(token: string) {
  const res = await fetchWithTimeout(
    `${base}/api/deploy/requests`,
    { headers: { "content-type": "application/json", ...withAuth(token) } },
    "list deploy requests"
  );
  return res.json() as Promise<{ requests: DeployRequestItem[] } | DeployRequestItem[]>;
}

export async function createDeployRequest(
  token: string,
  payload: Partial<DeployRequestItem>
) {
  const res = await fetchWithTimeout(
    `${base}/api/deploy/requests`,
    {
      method: "POST",
      headers: { "content-type": "application/json", ...withAuth(token) },
      body: JSON.stringify(payload),
    },
    "create deploy request"
  );
  return res.json() as Promise<DeployRequestItem>;
}

export async function approveDeployRequest(token: string, id: string | number) {
  await fetchWithTimeout(
    `${base}/api/deploy/requests/${id}/approve`,
    { method: "POST", headers: { ...withAuth(token) } },
    "approve deploy request"
  );
}

export async function rejectDeployRequest(token: string, id: string | number) {
  await fetchWithTimeout(
    `${base}/api/deploy/requests/${id}/reject`,
    { method: "POST", headers: { ...withAuth(token) } },
    "reject deploy request"
  );
}

export async function deployRequestById(token: string, id: string | number) {
  await fetchWithTimeout(
    `${base}/api/deploy/requests/${id}/deploy`,
    { method: "POST", headers: { ...withAuth(token) } },
    "deploy request"
  );
}

export type CostAnalysisArgs = {
  subscription_id: string;
  start_date: string;
  end_date: string;
  group_by?: string[] | null;
  include_forecast?: boolean;
  include_recommendations?: boolean;
};

export async function analyzeCosts(token: string, args: CostAnalysisArgs) {
  const res = await fetchWithTimeout(
    `${base}/api/cost/analysis`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...withAuth(token),
      },
      body: JSON.stringify({
        subscription_id: args.subscription_id,
        start_date: args.start_date,
        end_date: args.end_date,
        group_by: args.group_by ?? null,
        include_forecast: !!args.include_forecast,
        include_recommendations: !!args.include_recommendations,
      }),
    },
    "analyze costs"
  );
  return res.json();
}

export async function auditLogs(
  token: string,
  params?: {
    start_date?: string;
    end_date?: string;
    user_id?: string;
    page?: number;
    page_size?: number;
  }
) {
  const q = new URLSearchParams();
  if (params?.start_date) q.set("start_date", params.start_date);
  if (params?.end_date) q.set("end_date", params.end_date);
  if (params?.user_id) q.set("user_id", params.user_id);
  if (params?.page) q.set("page", String(params.page));
  if (params?.page_size) q.set("page_size", String(params.page_size));

  const res = await fetchWithTimeout(
    `${base}/api/audit/logs?${q.toString()}`,
    { headers: { ...withAuth(token) } },
    "audit logs"
  );
  return res.json();
}

export async function metrics(token: string) {
  const res = await fetchWithTimeout(
    `${base}/api/metrics`,
    {
      headers: { ...withAuth(token) },
    },
    "metrics"
  );
  return res.json();
}

export async function apiHealthz(): Promise<{ status: string }> {
  const res = await fetchWithTimeout(`${base}/api/health`, {}, "healthz");
  return res.json();
}

export async function apiStatus(): Promise<any> {
  const res = await fetchWithTimeout(`${base}/api/status`, {}, "status");
  return res.json();
}
