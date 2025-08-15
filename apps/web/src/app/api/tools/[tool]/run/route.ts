import { NextResponse } from 'next/server'
import { getToolByName, validateInput } from '@/config/tools'
import { toolsClient } from '@/lib/toolsClient'
import { logger, tracer } from '@/lib/logger'

export async function POST(
    request: Request,
    { params }: { params: { tool: string } }
) {
    const span = tracer.startSpan(`tool.run.${params.tool}`)
    try {
        const body = await request.json()
        const tool = await getToolByName(params.tool)
        if (!tool) {
            span.setStatus({ code: 2, message: 'Tool not found' })
            return NextResponse.json(
                { error: { code: 'TOOL_NOT_FOUND', message: `Tool ${params.tool} not found` } },
                { status: 404 }
            )
        }
        const validation = validateInput(tool.input_schema, body)
        if (!validation.valid) {
            span.setStatus({ code: 2, message: 'Invalid input' })
            return NextResponse.json(
                { error: { code: 'INVALID_INPUT', message: 'Input validation failed', details: validation.errors } },
                { status: 400 }
            )
        }
        logger.info(`Running tool ${params.tool}`, { input: body })
        const result = await toolsClient.runTool(params.tool, body)
        span.setStatus({ code: 0 })
        return NextResponse.json(result)
    } catch (error) {
        span.setStatus({ code: 2, message: 'Tool execution failed' })
        logger.error(`Failed to run tool ${params.tool}`, { error })
        const details = error instanceof Error ? { message: error.message } : { message: String(error) }
        return NextResponse.json(
            { error: { code: 'EXECUTION_ERROR', message: 'Tool execution failed', details } },
            { status: 500 }
        )
    } finally {
        span.end()
    }
}
