import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import { immer } from "zustand/middleware/immer";
import { withErrorHandling } from "./error-boundary";

import {
  login as apiLogin,
  logout as apiLogout,
  refresh as apiRefresh,
  chatV2 as apiChatV2,
  splitModel,
  listDeployRequests,
  createDeployRequest,
  approveDeployRequest,
  rejectDeployRequest,
  deployRequestById,
  type ChatMsg,
  type DeployRequestItem,
} from "@/lib/api";

interface User {
  id: string;
  email: string;
  roles: string[];
  subscription_id?: string;
}

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  metadata?: Record<string, unknown>;
}

interface ChatState {
  messages: ChatMessage[];
  isLoading: boolean;
  error: string | null;
  currentModel: string;
  enableTools: boolean;
  addMessage: (message: Omit<ChatMessage, "id" | "timestamp">) => void;
  clearMessages: () => void;
  setModel: (model: string) => void;
  setEnableTools: (enable: boolean) => void;
  sendMessage: (content: string) => Promise<void>;
}

interface DeploymentRequest {
  id: string;
  status: "pending" | "approved" | "rejected" | "deployed" | "failed";
  request: string;
  environment: string;
  cost_estimate?: number;
  created_at: Date;
  updated_at: Date;
}

interface DeploymentState {
  requests: DeploymentRequest[];
  currentRequest: DeploymentRequest | null;
  isDeploying: boolean;
  fetchRequests: () => Promise<void>;
  createRequest: (request: Partial<DeploymentRequest>) => Promise<void>;
  approveRequest: (id: string) => Promise<void>;
  rejectRequest: (id: string) => Promise<void>;
  deployRequest: (id: string) => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  devtools(
    persist(
      immer((set, get) => ({
        user: null,
        token: null,
        isAuthenticated: false,
        login: withErrorHandling("auth/login", async (email: string, password: string) => {
          try {
            const data = await apiLogin(email, password);
            set((state) => {
              state.user = data.user as User;
              state.token = data.access_token;
              state.isAuthenticated = true;
            });
          } catch (err: unknown) {
            let message = "Login failed";
            if (err instanceof Error) {
              message = err.message;
            } else if (
              err &&
              typeof err === "object" &&
              "detail" in err &&
              typeof (err as { detail?: unknown }).detail === "string"
            ) {
              message = (err as { detail: string }).detail;
            }
            throw new Error(message);
          }
        }),
        logout: withErrorHandling("auth/logout", async () => {
          const token = get().token;
          try {
            if (token) await apiLogout(token);
          } finally {
            set((state) => {
              state.user = null;
              state.token = null;
              state.isAuthenticated = false;
            });
          }
        }),
        refresh: withErrorHandling("auth/refresh", async () => {
          const token = get().token;
          if (!token) return;
          try {
            const data = await apiRefresh(token);
            set((state) => {
              state.token = data.access_token;
              state.isAuthenticated = true;
            });
          } catch {
            await get().logout();
          }
        }),
      })),
      {
        name: "auth-storage",
        partialize: (state) => ({ token: state.token, user: state.user }),
      }
    )
  )
);

function toChatHistory(messages: ChatMessage[]): ChatMsg[] {
  return messages.slice(-10).map((m) => ({ role: m.role, content: m.content }));
}

function toDeployment(d: DeployRequestItem): DeploymentRequest {
  return {
    id: String(d.id),
    status: d.status,
    request: d.request,
    environment: d.environment,
    cost_estimate: typeof d.cost_estimate === "number" ? d.cost_estimate : undefined,
    created_at: new Date(d.created_at),
    updated_at: new Date(d.updated_at),
  };
}

export const useChatStore = create<ChatState>()(
  devtools(
    immer((set, get) => ({
      messages: [],
      isLoading: false,
      error: null,
      currentModel: "openai:gpt-4o",
      enableTools: false,
      addMessage: (message) => {
        set((state) => {
          state.messages.push({
            ...message,
            id: crypto.randomUUID(),
            timestamp: new Date(),
          });
        });
      },
      clearMessages: () => {
        set((state) => {
          state.messages = [];
          state.error = null;
        });
      },
      setModel: (model) => {
        set((state) => {
          state.currentModel = model;
        });
      },
      setEnableTools: (enable) => {
        set((state) => {
          state.enableTools = enable;
        });
      },
      sendMessage: withErrorHandling("chat/send", async (content: string) => {
        const { token } = useAuthStore.getState();
        if (!token) throw new Error("Not authenticated");
        set((state) => {
          state.isLoading = true;
          state.error = null;
        });
        get().addMessage({ role: "user", content });
        try {
          const { provider, model } = splitModel(get().currentModel);
          const payload = {
            input: content,
            memory: toChatHistory(get().messages),
            provider,
            model,
            enable_tools: get().enableTools,
          };
          const data = await apiChatV2(token, payload);
          get().addMessage({ role: "assistant", content: data.response });
        } catch (error) {
          set((state) => {
            state.error = error instanceof Error ? error.message : "Unknown error";
          });
          throw error;
        } finally {
          set((state) => {
            state.isLoading = false;
          });
        }
      }),
    }))
  )
);

export const useDeploymentStore = create<DeploymentState>()(
  devtools(
    immer((set, get) => ({
      requests: [],
      currentRequest: null,
      isDeploying: false,
      fetchRequests: withErrorHandling("deploy/fetch", async () => {
        const { token } = useAuthStore.getState();
        if (!token) return;
        const data = await listDeployRequests(token);
        const list = Array.isArray(data) ? data : data.requests;
        set((state) => {
          state.requests = (list || []).map(toDeployment);
        });
      }),
      createRequest: withErrorHandling("deploy/create", async (request) => {
        const { token } = useAuthStore.getState();
        if (!token) throw new Error("Not authenticated");
        const created = await createDeployRequest(token, request as any);
        set((state) => {
          state.requests.push(toDeployment(created));
        });
      }),
      approveRequest: withErrorHandling("deploy/approve", async (id) => {
        const { token } = useAuthStore.getState();
        if (!token) throw new Error("Not authenticated");
        await approveDeployRequest(token, id);
        set((state) => {
          const r = state.requests.find((x) => x.id === id);
          if (r) {
            r.status = "approved";
            r.updated_at = new Date();
          }
        });
      }),
      rejectRequest: withErrorHandling("deploy/reject", async (id) => {
        const { token } = useAuthStore.getState();
        if (!token) throw new Error("Not authenticated");
        await rejectDeployRequest(token, id);
        set((state) => {
          const r = state.requests.find((x) => x.id === id);
          if (r) {
            r.status = "rejected";
            r.updated_at = new Date();
          }
        });
      }),
      deployRequest: withErrorHandling("deploy/deploy", async (id) => {
        const { token } = useAuthStore.getState();
        if (!token) throw new Error("Not authenticated");
        set((state) => {
          state.isDeploying = true;
        });
        try {
          await deployRequestById(token, id);
          set((state) => {
            const r = state.requests.find((x) => x.id === id);
            if (r) {
              r.status = "deployed";
              r.updated_at = new Date();
            }
          });
        } finally {
          set((state) => {
            state.isDeploying = false;
          });
        }
      }),
    }))
  )
);
