'use client'

import { useState } from 'react'
import { useTools } from '@/hooks/useTools'
import ToolForm from './ToolForm'
import ResultView from './ResultView'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { Terminal, ChevronRight, Loader2 } from 'lucide-react'

interface ToolsPanelProps {
    selectedTool: string | null
    onSelectTool: (tool: string | null) => void
    onToolExecuted?: (tool: string, input: any, output: any) => void
}

export default function ToolsPanel({ selectedTool, onSelectTool, onToolExecuted }: ToolsPanelProps) {
    const { tools, loading, error } = useTools()
    const [executionResult, setExecutionResult] = useState<any>(null)
    const [executing, setExecuting] = useState(false)
    const [executionError, setExecutionError] = useState<string | null>(null)

    const handleExecute = async (toolName: string, input: any) => {
        setExecuting(true)
        setExecutionError(null)
        setExecutionResult(null)
        try {
            const response = await fetch(`/api/tools/${toolName}/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify(input)
            })
            if (!response.ok) {
                const text = await response.text().catch(() => '')
                let message = text || `HTTP ${response.status}`
                try {
                    const parsed = JSON.parse(text)
                    message = parsed?.error?.message || message
                } catch { }
                throw new Error(message)
            }
            const result = await response.json()
            setExecutionResult(result)
            if (onToolExecuted) onToolExecuted(toolName, input, result)
        } catch (e: any) {
            setExecutionError(e?.message || 'Unknown error occurred')
        } finally {
            setExecuting(false)
        }
    }

    const selectedToolData = tools.find(t => t.name === selectedTool)

    return (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <div className="lg:col-span-1">
                <Card className="glass">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                            <Terminal className="h-5 w-5" />
                            Available Tools
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        {loading && (
                            <div className="flex items-center justify-center py-8">
                                <Loader2 className="h-6 w-6 animate-spin" />
                            </div>
                        )}
                        {error && (
                            <div className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
                                {error}
                            </div>
                        )}
                        <ScrollArea className="h-[500px]">
                            <div className="space-y-3">
                                {tools.map(tool => (
                                    <Card
                                        key={tool.name}
                                        className={`cursor-pointer transition-all hover:shadow-md ${selectedTool === tool.name ? 'border-primary ring-2 ring-primary/20' : ''
                                            }`}
                                        onClick={() => onSelectTool(tool.name)}
                                    >
                                        <CardContent className="p-4">
                                            <div className="flex items-start justify-between">
                                                <div className="flex-1">
                                                    <h3 className="font-semibold">{tool.title}</h3>
                                                    <p className="mt-1 text-sm text-muted-foreground">
                                                        {tool.description}
                                                    </p>
                                                </div>
                                                <ChevronRight className="h-5 w-5 text-muted-foreground" />
                                            </div>
                                            <div className="mt-3 flex flex-wrap gap-2">
                                                <Badge variant="outline" className="text-xs">
                                                    {Object.keys(tool.schema.input.properties || {}).length} inputs
                                                </Badge>
                                                <Badge variant="outline" className="text-xs">
                                                    {Object.keys(tool.schema.output.properties || {}).length} outputs
                                                </Badge>
                                            </div>
                                        </CardContent>
                                    </Card>
                                ))}
                            </div>
                        </ScrollArea>
                    </CardContent>
                </Card>
            </div>

            <div className="lg:col-span-2 space-y-6">
                {selectedToolData ? (
                    <>
                        <Card className="glass">
                            <CardHeader>
                                <CardTitle>{selectedToolData.title}</CardTitle>
                            </CardHeader>
                            <CardContent>
                                <p className="text-muted-foreground mb-6">
                                    {selectedToolData.description}
                                </p>
                                <ToolForm
                                    schema={selectedToolData.schema.input}
                                    onSubmit={(data) => handleExecute(selectedToolData.name, data)}
                                    isLoading={executing}
                                />
                            </CardContent>
                        </Card>

                        {(executionResult || executionError) && (
                            <ResultView
                                result={executionResult}
                                error={executionError}
                                schema={selectedToolData.schema.output}
                            />
                        )}
                    </>
                ) : (
                    <Card className="glass">
                        <CardContent className="flex flex-col items-center justify-center py-16">
                            <Terminal className="h-12 w-12 text-muted-foreground mb-4" />
                            <p className="text-lg font-medium">Select a tool to get started</p>
                            <p className="text-sm text-muted-foreground mt-2">
                                Choose from the available tools on the left
                            </p>
                        </CardContent>
                    </Card>
                )}
            </div>
        </div>
    )
}
