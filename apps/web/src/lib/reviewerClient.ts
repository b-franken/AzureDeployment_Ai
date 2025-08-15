import { logger } from './logger'

interface ReviewRequest {
    model: string
    toolName: string
    input: any
    output: any
}

interface ReviewResponse {
    verdict: 'approved' | 'needs_revision' | 'rejected'
    summary: string
    suggestions: string[]
}

class ReviewerClient {
    private endpoint: string

    constructor() {
        this.endpoint = process.env.REVIEWER_ENDPOINT || ''
    }

    async review(request: ReviewRequest): Promise<ReviewResponse> {
        if (!this.endpoint) {
            return this.getMockReview(request)
        }
        try {
            const response = await fetch(this.endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(request)
            })
            if (!response.ok) {
                throw new Error(`Review failed: ${response.status}`)
            }
            return await response.json()
        } catch (error) {
            logger.error('Review request failed', { error })
            return this.getMockReview(request)
        }
    }

    private getMockReview(request: ReviewRequest): ReviewResponse {
        logger.info('Generating mock review', { model: request.model, tool: request.toolName })
        const reviews: Record<string, ReviewResponse> = {
            'openai:gpt-4o': {
                verdict: 'approved',
                summary: 'The tool execution completed successfully with expected outputs.',
                suggestions: ['Consider adding more detailed logging', 'Resource naming could follow convention better']
            },
            'anthropic:claude-3-5-sonnet': {
                verdict: 'needs_revision',
                summary: 'Output is functional but could be optimized.',
                suggestions: ['Implement retry logic for transient failures', 'Add validation for edge cases', 'Consider performance implications at scale']
            },
            default: {
                verdict: 'approved',
                summary: `Mock review using ${request.model} for ${request.toolName}`,
                suggestions: ['No specific suggestions in mock mode']
            }
        }
        const exact = reviews[request.model]
        if (exact) return exact
        const match = Object.keys(reviews).find(k => k !== 'default' && request.model.includes(k.split(':')[1] || ''))
        return reviews[match || 'default']
    }
}

export const reviewerClient = new ReviewerClient()
