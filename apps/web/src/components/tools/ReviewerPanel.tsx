'use client'

import { useState } from 'react'
import { useReviewer } from '@/hooks/useReviewer'
import { AVAILABLE_LLM_MODELS } from '@/config/models'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Sparkles, ChevronDown, Loader2 } from 'lucide-react'

interface ReviewerPanelProps {
    toolName: string
    input: any
    output: any
}

export default function ReviewerPanel({ toolName, input, output }: ReviewerPanelProps) {
    const [selectedModel, setSelectedModel] = useState('openai:gpt-4o')
    const [showModelDropdown, setShowModelDropdown] = useState(false)
    const { review, loading, error, submitReview } = useReviewer()

    const handleReview = () => {
        submitReview({
            model: selectedModel,
            toolName,
            input,
            output
        })
    }

    const getVerdictColor = (verdict?: string) => {
        switch (verdict) {
            case 'approved':
                return 'bg-green-500/10 text-green-600 border-green-500/20'
            case 'needs_revision':
                return 'bg-yellow-500/10 text-yellow-600 border-yellow-500/20'
            case 'rejected':
                return 'bg-red-500/10 text-red-600 border-red-500/20'
            default:
                return ''
        }
    }

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-3">
                <div className="relative">
                    <Button
                        variant="outline"
                        onClick={() => setShowModelDropdown(!showModelDropdown)}
                        className="min-w-[200px] justify-between"
                    >
                        <span className="truncate">
                            {AVAILABLE_LLM_MODELS.find(m => m.id === selectedModel)?.displayName || selectedModel}
                        </span>
                        <ChevronDown className="ml-2 h-4 w-4" />
                    </Button>

                    {showModelDropdown && (
                        <div className="absolute top-full left-0 z-50 mt-2 w-[300px] rounded-lg border bg-background shadow-lg">
                            <div className="max-h-[300px] overflow-auto p-2">
                                {AVAILABLE_LLM_MODELS.map(model => (
                                    <button
                                        key={model.id}
                                        onClick={() => {
                                            setSelectedModel(model.id)
                                            setShowModelDropdown(false)
                                        }}
                                        className={`w-full rounded-md px-3 py-2 text-left text-sm hover:bg-muted ${selectedModel === model.id ? 'bg-muted' : ''
                                            }`}
                                    >
                                        <div className="font-medium">{model.displayName}</div>
                                        <div className="text-xs text-muted-foreground">
                                            {model.provider} • {model.maxTokens ? `${model.maxTokens.toLocaleString()} tokens` : 'Local'}
                                        </div>
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                <Button onClick={handleReview} disabled={loading}>
                    {loading ? (
                        <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            Reviewing...
                        </>
                    ) : (
                        <>
                            <Sparkles className="mr-2 h-4 w-4" />
                            Review Execution
                        </>
                    )}
                </Button>
            </div>

            {review && (
                <Card className="glass">
                    <CardHeader>
                        <div className="flex items-center justify-between">
                            <CardTitle className="text-lg">AI Review Result</CardTitle>
                            <Badge className={getVerdictColor(review.verdict)}>
                                {review.verdict?.replace('_', ' ').toUpperCase()}
                            </Badge>
                        </div>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <div>
                            <h4 className="font-medium text-sm mb-2">Summary</h4>
                            <p className="text-sm text-muted-foreground">{review.summary}</p>
                        </div>

                        {review.suggestions && review.suggestions.length > 0 && (
                            <div>
                                <h4 className="font-medium text-sm mb-2">Suggestions</h4>
                                <ul className="list-disc list-inside space-y-1">
                                    {review.suggestions.map((suggestion, i) => (
                                        <li key={i} className="text-sm text-muted-foreground">
                                            {suggestion}
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        )}
                    </CardContent>
                </Card>
            )}

            {error && (
                <div className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
                    {error}
                </div>
            )}
        </div>
    )
}