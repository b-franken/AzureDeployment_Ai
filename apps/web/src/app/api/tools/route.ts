import { NextResponse } from 'next/server'
import { getToolsManifest } from '@/config/tools'
import { logger } from '@/lib/logger'

export async function GET() {
    try {
        logger.info('Fetching tools manifest')
        const manifest = await getToolsManifest()
        return NextResponse.json({
            tools: manifest.map(tool => ({
                name: tool.name,
                title: tool.title,
                description: tool.description,
                schema: {
                    input: tool.input_schema,
                    output: tool.output_schema
                }
            }))
        })
    } catch (error) {
        logger.error('Failed to fetch tools', { error })
        const details = error instanceof Error ? { message: error.message } : { message: String(error) }
        return NextResponse.json(
            { error: { code: 'TOOLS_FETCH_ERROR', message: 'Failed to fetch tools', details } },
            { status: 500 }
        )
    }
}
