'use client'

import { useState } from 'react'
import ToolsPanel from '@/components/tools/ToolsPanel'
import ReviewerPanel from '@/components/tools/ReviewerPanel'
import { Button } from '@/components/ui/button'
import { ArrowLeft } from 'lucide-react'
import Link from 'next/link'

export default function ToolsPage() {
    const [selectedTool, setSelectedTool] = useState<string | null>(null)
    const [lastExecution, setLastExecution] = useState<{
        tool: string
        input: any
        output: any
    } | null>(null)

    return (
        <div className="container mx-auto px-4 py-8">
            <div className="mb-6 flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <Link href="/">
                        <Button variant="ghost" size="icon">
                            <ArrowLeft className="h-5 w-5" />
                        </Button>
                    </Link>
                    <h1 className="text-3xl font-bold">DevOps Tools</h1>
                </div>
                {lastExecution && (
                    <ReviewerPanel
                        toolName={lastExecution.tool}
                        input={lastExecution.input}
                        output={lastExecution.output}
                    />
                )}
            </div>

            <ToolsPanel
                selectedTool={selectedTool}
                onSelectTool={setSelectedTool}
                onToolExecuted={(tool, input, output) => {
                    setLastExecution({ tool, input, output })
                }}
            />
        </div>
    )
}
