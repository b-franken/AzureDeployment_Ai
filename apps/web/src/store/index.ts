import { create } from 'zustand'
import { devtools, persist } from 'zustand/middleware'
import { immer } from 'zustand/middleware/immer'

interface User {
  id: string
  email: string
  roles: string[]
  subscription_id?: string
}

interface AuthState {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  metadata?: Record<string, any>
}

interface ChatState {
  messages: ChatMessage[]
  isLoading: boolean
  error: string | null
  currentModel: string
  enableTools: boolean
  addMessage: (message: Omit<ChatMessage, 'id' | 'timestamp'>) => void
  clearMessages: () => void
  setModel: (model: string) => void
  setEnableTools: (enable: boolean) => void
  sendMessage: (content: string) => Promise<void>
}

interface DeploymentRequest {
  id: string
  status: 'pending' | 'approved' | 'rejected' | 'deployed' | 'failed'
  request: string
  environment: string
  cost_estimate?: number
  created_at: Date
  updated_at: Date
}

interface DeploymentState {
  requests: DeploymentRequest[]
  currentRequest: DeploymentRequest | null
  isDeploying: boolean
  fetchRequests: () => Promise<void>
  createRequest: (request: Partial<DeploymentRequest>) => Promise<void>
  approveRequest: (id: string) => Promise<void>
  rejectRequest: (id: string) => Promise<void>
  deployRequest: (id: string) => Promise<void>
}

type Json = Record<string, unknown>

export const useAuthStore = create<AuthState>()(
  devtools(
    persist(
      immer((set, get) => ({
        user: null,
        token: null,
        isAuthenticated: false,
        login: async (email: string, password: string) => {
          const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
            body: JSON.stringify({ email, password })
          })
          if (!response.ok) {
            let message = 'Login failed'
            try {
              const err = (await response.json()) as Json
              if (typeof err.detail === 'string') message = err.detail
            } catch {}
            throw new Error(message)
          }
          const data = (await response.json()) as { user: User; access_token: string }
          set(state => {
            state.user = data.user
            state.token = data.access_token
            state.isAuthenticated = true
          })
        },
        logout: async () => {
          const token = get().token
          try {
            if (token) {
              await fetch('/api/auth/logout', {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' }
              })
            }
          } finally {
            set(state => {
              state.user = null
              state.token = null
              state.isAuthenticated = false
            })
          }
        },
        refresh: async () => {
          const token = get().token
          if (!token) return
          const response = await fetch('/api/auth/refresh', {
            method: 'POST',
            headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' }
          })
          if (response.ok) {
            const data = (await response.json()) as { access_token: string }
            set(state => {
              state.token = data.access_token
              state.isAuthenticated = true
            })
          } else {
            await get().logout()
          }
        }
      })),
      {
        name: 'auth-storage',
        partialize: state => ({ token: state.token, user: state.user })
      }
    )
  )
)

async function apiFetch<T>(path: string, init: RequestInit = {}, withAuth = true): Promise<T> {
  const { token } = useAuthStore.getState()
  const headers: HeadersInit = {
    Accept: 'application/json',
    ...(init.body ? { 'Content-Type': 'application/json' } : {}),
    ...(withAuth && token ? { Authorization: `Bearer ${token}` } : {})
  }
  const res = await fetch(path, { ...init, headers: { ...headers, ...(init.headers || {}) } })
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const err = (await res.json()) as Json
      if (typeof err.detail === 'string') message = err.detail
      if (typeof err.message === 'string') message = err.message
    } catch {}
    throw new Error(message)
  }
  if (res.status === 204) return undefined as unknown as T
  return (await res.json()) as T
}

function toDeployment(d: any): DeploymentRequest {
  return {
    id: String(d.id),
    status: d.status,
    request: d.request,
    environment: d.environment,
    cost_estimate: typeof d.cost_estimate === 'number' ? d.cost_estimate : undefined,
    created_at: new Date(d.created_at),
    updated_at: new Date(d.updated_at)
  }
}

export const useChatStore = create<ChatState>()(
  devtools(
    immer((set, get) => ({
      messages: [],
      isLoading: false,
      error: null,
      currentModel: 'openai:gpt-4o',
      enableTools: false,
      addMessage: message => {
        set(state => {
          state.messages.push({
            ...message,
            id: crypto.randomUUID(),
            timestamp: new Date()
          })
        })
      },
      clearMessages: () => {
        set(state => {
          state.messages = []
          state.error = null
        })
      },
      setModel: model => {
        set(state => {
          state.currentModel = model
        })
      },
      setEnableTools: enable => {
        set(state => {
          state.enableTools = enable
        })
      },
      sendMessage: async content => {
        const { token } = useAuthStore.getState()
        if (!token) throw new Error('Not authenticated')
        set(state => {
          state.isLoading = true
          state.error = null
        })
        get().addMessage({ role: 'user', content })
        try {
          const payload = {
            input: content,
            memory: get()
              .messages.slice(-10)
              .map(m => ({ role: m.role, content: m.content })),
            model: get().currentModel,
            enable_tools: get().enableTools
          }
          const data = await apiFetch<{ response: string }>('/api/chat/v2', {
            method: 'POST',
            body: JSON.stringify(payload)
          })
          get().addMessage({ role: 'assistant', content: data.response })
        } catch (error) {
          set(state => {
            state.error = error instanceof Error ? error.message : 'Unknown error'
          })
        } finally {
          set(state => {
            state.isLoading = false
          })
        }
      }
    }))
  )
)

export const useDeploymentStore = create<DeploymentState>()(
  devtools(
    immer((set, get) => ({
      requests: [],
      currentRequest: null,
      isDeploying: false,
      fetchRequests: async () => {
        const { token } = useAuthStore.getState()
        if (!token) return
        const data = await apiFetch<{ requests: any[] } | any[]>('/api/deploy/requests', {
          method: 'GET'
        })
        const list = Array.isArray(data) ? data : data.requests
        set(state => {
          state.requests = (list || []).map(toDeployment)
        })
      },
      createRequest: async request => {
        const { token } = useAuthStore.getState()
        if (!token) throw new Error('Not authenticated')
        const data = await apiFetch<any>('/api/deploy/requests', {
          method: 'POST',
          body: JSON.stringify(request)
        })
        set(state => {
          state.requests.push(toDeployment(data))
        })
      },
      approveRequest: async id => {
        const { token } = useAuthStore.getState()
        if (!token) throw new Error('Not authenticated')
        await apiFetch<void>(`/api/deploy/requests/${id}/approve`, { method: 'POST' })
        set(state => {
          const r = state.requests.find(x => x.id === id)
          if (r) {
            r.status = 'approved'
            r.updated_at = new Date()
          }
        })
      },
      rejectRequest: async id => {
        const { token } = useAuthStore.getState()
        if (!token) throw new Error('Not authenticated')
        await apiFetch<void>(`/api/deploy/requests/${id}/reject`, { method: 'POST' })
        set(state => {
          const r = state.requests.find(x => x.id === id)
          if (r) {
            r.status = 'rejected'
            r.updated_at = new Date()
          }
        })
      },
      deployRequest: async id => {
        const { token } = useAuthStore.getState()
        if (!token) throw new Error('Not authenticated')
        set(state => {
          state.isDeploying = true
        })
        try {
          await apiFetch<void>(`/api/deploy/requests/${id}/deploy`, { method: 'POST' })
          set(state => {
            const r = state.requests.find(x => x.id === id)
            if (r) {
              r.status = 'deployed'
              r.updated_at = new Date()
            }
          })
        } finally {
          set(state => {
            state.isDeploying = false
          })
        }
      }
    }))
  )
)
