/**
 * Memory API client for user conversation management
 * 
 * Provides TypeScript client functions for interacting with the memory service,
 * enabling persistent conversation context and smart AI interactions.
 */

import { API_BASE_URL } from "./api"

export interface ConversationMessage {
    role: "user" | "assistant" | "system" | "tool"
    content: string
    timestamp?: string
    metadata?: Record<string, any>
}

export interface ConversationHistory {
    user_id: string
    messages: ConversationMessage[]
    total_count: number
    thread_id: string | null
    has_more: boolean
}

export interface MessageSearchResult {
    user_id: string
    query: string
    results: ConversationMessage[]
    total_found: number
}

export interface UserMemoryStats {
    user_id: string
    total_messages: number
    recent_user_messages: number
    recent_assistant_messages: number
    memory_utilization_percent: number
    max_memory_limit: number
}

/**
 * Fetch user's conversation history with optional filtering
 */
export async function getConversationHistory(options?: {
    limit?: number
    threadId?: string
    includeMetadata?: boolean
    signal?: AbortSignal
}): Promise<ConversationHistory> {
    const params = new URLSearchParams()
    
    if (options?.limit) params.append('limit', options.limit.toString())
    if (options?.threadId) params.append('thread_id', options.threadId)
    if (options?.includeMetadata) params.append('include_metadata', 'true')
    
    const url = `${API_BASE_URL}/memory/history${params.toString() ? `?${params}` : ''}`
    
    const response = await fetch(url, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
        },
        signal: options?.signal,
    })
    
    if (!response.ok) {
        throw new Error(`Failed to fetch conversation history: ${response.statusText}`)
    }
    
    return response.json()
}

/**
 * Search through user's message history
 */
export async function searchMessages(
    query: string,
    options?: {
        limit?: number
        threadId?: string
        signal?: AbortSignal
    }
): Promise<MessageSearchResult> {
    const response = await fetch(`${API_BASE_URL}/memory/search`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            query,
            limit: options?.limit || 10,
            thread_id: options?.threadId,
        }),
        signal: options?.signal,
    })
    
    if (!response.ok) {
        throw new Error(`Failed to search messages: ${response.statusText}`)
    }
    
    return response.json()
}

/**
 * Get comprehensive memory usage statistics
 */
export async function getMemoryStats(signal?: AbortSignal): Promise<UserMemoryStats> {
    const response = await fetch(`${API_BASE_URL}/memory/stats`, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
        },
        signal,
    })
    
    if (!response.ok) {
        throw new Error(`Failed to fetch memory stats: ${response.statusText}`)
    }
    
    return response.json()
}

/**
 * Clear user's conversation memory
 * WARNING: This action is irreversible
 */
export async function clearMemory(options?: {
    threadId?: string
    signal?: AbortSignal
}): Promise<{ message: string; deleted_messages: number; user_id: string }> {
    const params = new URLSearchParams()
    if (options?.threadId) params.append('thread_id', options.threadId)
    
    const url = `${API_BASE_URL}/memory/clear${params.toString() ? `?${params}` : ''}`
    
    const response = await fetch(url, {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json',
        },
        signal: options?.signal,
    })
    
    if (!response.ok) {
        throw new Error(`Failed to clear memory: ${response.statusText}`)
    }
    
    return response.json()
}

/**
 * Load initial conversation context when starting a chat session
 */
export async function loadConversationContext(threadId?: string): Promise<ConversationMessage[]> {
    try {
        const history = await getConversationHistory({
            limit: 10, // Load last 10 messages for context
            threadId,
            includeMetadata: false
        })
        
        console.log(`Loaded ${history.messages.length} messages from conversation history`)
        return history.messages
    } catch (error) {
        console.warn('Failed to load conversation context:', error)
        return []
    }
}

/**
 * Check if user has significant conversation history
 */
export async function hasConversationHistory(): Promise<boolean> {
    try {
        const stats = await getMemoryStats()
        return stats.total_messages > 0
    } catch (error) {
        console.warn('Failed to check conversation history:', error)
        return false
    }
}