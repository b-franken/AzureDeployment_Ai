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

export const useAuthStore = create<AuthState>()(
    devtools(
        persist(
            immer((set, get) => ({
                user: null,
                token: null,
                isAuthenticated: false,

                login: async (email: string, password: string) => {
                    const response = await fetch('/api/v2/auth/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email, password })
                    })

                    if (!response.ok) {
                        throw new Error('Login failed')
                    }

                    const data = await response.json()

                    set(state => {
                        state.user = data.user
                        state.token = data.access_token
                        state.isAuthenticated = true
                    })
                },

                logout: async () => {
                    const token = get().token
                    if (token) {
                        await fetch('/api/v2/auth/logout', {
                            method: 'POST',
                            headers: {
                                'Authorization': `Bearer ${token}`
                            }
                        })
                    }

                    set(state => {
                        state.user = null
                        state.token = null
                        state.isAuthenticated = false
                    })
                },

                refresh: async () => {
                    const token = get().token
                    if (!token) return

                    const response = await fetch('/api/v2/auth/refresh', {
                        method: 'POST',
                        headers: {
                            'Authorization': `Bearer ${token}`
                        }
                    })

                    if (response.ok) {
                        const data = await response.json()
                        set(state => {
                            state.token = data.access_token
                        })
                    } else {
                        get().logout()
                    }
                }
            })),
            {
                name: 'auth-storage',
                partialize: (state) => ({
                    token: state.token,
                    user: state.user
                })
            }
        )
    )
)

export const useChatStore = create<ChatState>()(
    devtools(
        immer((set, get) => ({
            messages: [],
            isLoading: false,
            error: null,
            currentModel: 'openai:gpt-4o',
            enableTools: false,

            addMessage: (message) => {
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

            setModel: (model) => {
                set(state => {
                    state.currentModel = model
                })
            },

            setEnableTools: (enable) => {
                set(state => {
                    state.enableTools = enable
                })
            },

            sendMessage: async (content) => {
                const { token } = useAuthStore.getState()
                if (!token) throw new Error('Not authenticated')

                set(state => {
                    state.isLoading = true
                    state.error = null
                })

                get().addMessage({ role: 'user', content })

                try {
                    const response = await fetch('/api/v2/chat/chat', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${token}`
                        },
                        body: JSON.stringify({
                            input: content,
                            memory: get().messages.slice(-10),
                            model: get().currentModel,
                            enable_tools: get().enableTools
                        })
                    })

                    if (!response.ok) {
                        throw new Error('Chat request failed')
                    }

                    const data = await response.json()
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

                const response = await fetch('/api/v2/deploy/requests', {
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                })

                if (response.ok) {
                    const data = await response.json()
                    set(state => {
                        state.requests = data.requests
                    })
                }
            },

            createRequest: async (request) => {
                const { token } = useAuthStore.getState()
                if (!token) throw new Error('Not authenticated')

                const response = await fetch('/api/v2/deploy/requests', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`
                    },
                    body: JSON.stringify(request)
                })

                if (!response.ok) {
                    throw new Error('Failed to create deployment request')
                }

                const data = await response.json()
                set(state => {
                    state.requests.push(data)
                })
            },

            approveRequest: async (id) => {
                const { token } = useAuthStore.getState()
                if (!token) throw new Error('Not authenticated')

                const response = await fetch(`/api/v2/deploy/requests/${id}/approve`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                })

                if (!response.ok) {
                    throw new Error('Failed to approve request')
                }

                set(state => {
                    const request = state.requests.find(r => r.id === id)
                    if (request) {
                        request.status = 'approved'
                        request.updated_at = new Date()
                    }
                })
            },

            rejectRequest: async (id) => {
                const { token } = useAuthStore.getState()
                if (!token) throw new Error('Not authenticated')

                const response = await fetch(`/api/v2/deploy/requests/${id}/reject`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                })

                if (!response.ok) {
                    throw new Error('Failed to reject request')
                }

                set(state => {
                    const request = state.requests.find(r => r.id === id)
                    if (request) {
                        request.status = 'rejected'
                        request.updated_at = new Date()
                    }
                })
            },

            deployRequest: async (id) => {
                const { token } = useAuthStore.getState()
                if (!token) throw new Error('Not authenticated')

                set(state => {
                    state.isDeploying = true
                })

                try {
                    const response = await fetch(`/api/v2/deploy/requests/${id}/deploy`, {
                        method: 'POST',
                        headers: {
                            'Authorization': `Bearer ${token}`
                        }
                    })

                    if (!response.ok) {
                        throw new Error('Deployment failed')
                    }

                    set(state => {
                        const request = state.requests.find(r => r.id === id)
                        if (request) {
                            request.status = 'deployed'
                            request.updated_at = new Date()
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