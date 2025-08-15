'use client'

import { useState } from 'react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Copy, Check, AlertCircle, CheckCircle2, XCircle } from 'lucide-react'

interface ResultViewProps {
    result?: any
    error?: string | null
    schema?: any
}

export default function ResultView({ result, error }: ResultViewProps) {
    const [copied, setCopied] = useState(false)

    const handleCopy = () => {
        const content = result ? JSON.stringify(result, null, 2) : error || ''
        navigator.clipboard.writeText(content)
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
    }

    const getStatusIcon = (status?: string) => {
        switch (status) {
            case 'success':
                return <CheckCircle2 className="h-5 w-5 text-green-500" />
            case 'failed':
                return <XCircle className="h-5 w-5 text-destructive" />
            case 'pending':
                return <AlertCircle className="h-5 w-5 text-yellow-500" />
            default:
                return null
        }
    }

    return (
        <Card className={`glass ${error ? 'border-destructive' : ''}`}>
            <CardHeader>
                <div className="flex items-center justify-between">
                    <CardTitle className="flex items-center gap-2">
                        {error ? (
                            <>
                                <AlertCircle className="h-5 w-5 text-destructive" />
                                Execution Error
                            </>
                        ) : (
                            <>
                                {getStatusIcon(result?.status)}
                                Execution Result
                            </>
                        )}
                    </CardTitle>
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={handleCopy}
                        className="h-8 w-8"
                    >
                        {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                    </Button>
                </div>
            </CardHeader>
            <CardContent>
                {error ? (
                    <div className="rounded-lg bg-destructive/10 p-4">
                        <p className="text-sm text-destructive">{error}</p>
                    </div>
                ) : result ? (
                    <div className="space-y-4">
                        {result.status && (
                            <div className="flex items-center gap-2">
                                <span className="text-sm font-medium">Status:</span>
                                <Badge
                                    variant={
                                        result.status === 'success'
                                            ? 'default'
                                            : result.status === 'failed'
                                                ? 'destructive'
                                                : 'secondary'
                                    }
                                >
                                    {result.status}
                                </Badge>
                            </div>
                        )}
                        {result.message && (
                            <div>
                                <span className="text-sm font-medium">Message:</span>
                                <p className="mt-1 text-sm text-muted-foreground">{result.message}</p>
                            </div>
                        )}
                        <div>
                            <span className="text-sm font-medium">Raw Output:</span>
                            <pre className="mt-2 overflow-auto rounded-lg bg-muted p-3 text-xs">
                                {JSON.stringify(result, null, 2)}
                            </pre>
                        </div>
                    </div>
                ) : null}
            </CardContent>
        </Card>
    )
}
