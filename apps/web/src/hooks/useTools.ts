import { useState, useEffect, useCallback } from 'react'

export interface UiTool {
    name: string
    title: string
    description: string
    schema: {
        input: any
        output: any
    }
}

interface ToolsResponse {
    tools: UiTool[]
}

export function useTools() {
    const [tools, setTools] = useState<UiTool[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    const fetchTools = useCallback(async () => {
        try {
            setLoading(true)
            setError(null)

            const res = await fetch('/api/tools', { method: 'GET' })
            if (!res.ok) {
                const err = await res.json().catch(() => null)
                throw new Error(err?.error?.message || 'Failed to fetch tools')
            }

            const data: ToolsResponse = await res.json()
            setTools(Array.isArray(data.tools) ? data.tools : [])
        } catch (e: any) {
            setError(e?.message || 'Unknown error')
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        fetchTools()
    }, [fetchTools])

    return { tools, loading, error, refetch: fetchTools }
}
