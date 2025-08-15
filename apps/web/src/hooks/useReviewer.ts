import { useState, useCallback } from 'react'

export type ReviewVerdict = 'approved' | 'needs_revision' | 'rejected'

interface ReviewRequest {
    model: string
    toolName: string
    input: any
    output: any
}

interface ReviewResponse {
    verdict: ReviewVerdict
    summary: string
    suggestions: string[]
}

export function useReviewer() {
    const [review, setReview] = useState<ReviewResponse | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const submitReview = useCallback(async (request: ReviewRequest) => {
        try {
            setLoading(true)
            setError(null)

            const res = await fetch('/api/reviewer/review', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(request)
            })

            if (!res.ok) {
                const err = await res.json().catch(() => null)
                throw new Error(err?.error?.message || 'Review failed')
            }

            const data: ReviewResponse = await res.json()
            setReview(data)
        } catch (e: any) {
            setError(e?.message || 'Unknown error')
        } finally {
            setLoading(false)
        }
    }, [])

    const clearReview = useCallback(() => {
        setReview(null)
        setError(null)
    }, [])

    return { review, loading, error, submitReview, clearReview }
}
