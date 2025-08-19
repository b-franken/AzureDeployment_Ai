const base = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 30000;

export class ApiError extends Error {
  constructor(message: string, public cause?: unknown, public status?: number) {
    super(message);
    this.name = "ApiError";
  }
}

export type ChatMsg = { role: "user" | "assistant" | "system"; content: string };

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
      } catch { }
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


export async function chat(
  input: string,
  memory?: ChatMsg[],
  provider?: string | null,
  model?: string | null,
  enable_tools?: boolean,
  preferred_tool?: string | null,
  allowlist?: string[] | null
): Promise<string> {
  const res = await fetchWithTimeout(
    `${base}/api/chat`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        input,
        memory: memory || [],
        provider,
        model,
        enable_tools: enable_tools || false,
        preferred_tool,
        allowlist: allowlist || []
      }),
    },
    "chat"
  );
  const data = await res.json();
  return data.output;
}


export async function review_once(
  user_input: string,
  assistant_reply: string,
  opts?: { provider?: string | null; model?: string | null }
): Promise<string> {
  const res = await fetchWithTimeout(
    `${base}/api/review`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_input,
        assistant_reply,
        provider: opts?.provider,
        model: opts?.model,
      }),
    },
    "review"
  );
  const data = await res.json();
  return data.output;
}

export function splitModel(id: string): { provider: string | null; model: string | null } {
  if (!id) return { provider: null, model: null };
  const i = id.indexOf(":");
  if (i === -1) return { provider: null, model: id };
  return { provider: id.slice(0, i), model: id.slice(i + 1) };
}


export async function login(email: string, password: string) {
  console.log("Login called in development mode - returning mock token");
  return {
    access_token: "dev-token",
    token_type: "bearer",
    expires_in: 3600,
    user: { id: "dev", email: email, roles: ["user"] }
  };
}

export async function logout() {
  console.log("Logout called in development mode");
  return { message: "ok" };
}


export type AuthResult = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: { id: string; email: string; roles: string[] };
};

export type ChatV2Response = {
  response: string;
  correlation_id: string;
  processing_time: number;
};

export type ChatRequest = {
  input: string;
  memory?: ChatMsg[];
  provider?: string | null;
  model?: string | null;
  enable_tools?: boolean;
  preferred_tool?: string | null;
  allowlist?: string[] | null;
};

export type ReviewRequest = {
  user_input: string;
  assistant_reply: string;
  provider?: string | null;
  model?: string | null;
};


export async function apiHealthz(): Promise<{ status: string }> {
  const res = await fetch(`${base}/api/health`);
  return res.json();
}

export async function apiStatus(): Promise<any> {
  const res = await fetch(`${base}/api/status`);
  return res.json();
}