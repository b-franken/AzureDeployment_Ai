import { NextResponse } from 'next/server'
import { reviewerClient } from '@/lib/reviewerClient'
import { logger } from '@/lib/logger'
import { z } from 'zod'

const reviewRequestSchema = z.object({
    model: z.string(),
    toolName: z.string(),
    input: z.any(),
    output: z.any()
})

export async function POST(request: Request) {
    try {
        const body = await request.json()
        const validation = reviewRequestSchema.safeParse(body)
        if (!validation.success) {
            return NextResponse.json(
                { error: { code: 'INVALID_REQUEST', message: 'Invalid review request', details: validation.error } },
                { status: 400 }
            )
        }
        logger.info('Requesting review', { model: body.model, tool: body.toolName })
        const review = await reviewerClient.review({
            model: body.model,
            toolName: body.toolName,
            input: body.input,
            output: body.output
        })
        return NextResponse.json({
            verdict: review.verdict,
            summary: review.summary,
            suggestions: review.suggestions
        })
    } catch (error) {
        logger.error('Review failed', { error })
        const details = error instanceof Error ? { message: error.message } : { message: String(error) }
        return NextResponse.json(
            { error: { code: 'REVIEW_ERROR', message: 'Review failed', details } },
            { status: 500 }
        )
    }
}
