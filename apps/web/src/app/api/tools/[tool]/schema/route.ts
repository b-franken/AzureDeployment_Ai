import { NextResponse } from 'next/server'
import { getToolByName } from '@/config/tools'
import { logger } from '@/lib/logger'

export async function GET(
    request: Request,
    { params }: { params: { tool: string } }
) {
    try {
        const tool = await getToolByName(params.tool)
        if (!tool) {
            return NextResponse.json(
                { error: { code: 'TOOL_NOT_FOUND', message: `Tool ${params.tool} not found` } },
                { status: 404 }
            )
        }
        return NextResponse.json({
            input_schema: tool.input_schema,
            output_schema: tool.output_schema
        })
    } catch (error) {
        logger.error(`Failed to fetch schema for tool ${params.tool}`, { error })
        const details = error instanceof Error ? { message: error.message } : { message: String(error) }
        return NextResponse.json(
            { error: { code: 'SCHEMA_FETCH_ERROR', message: 'Failed to fetch schema', details } },
            { status: 500 }
        )
    }
}
