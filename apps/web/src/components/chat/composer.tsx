import * as React from 'react'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Send, RotateCcw, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
    value: string
    onChange: (v: string) => void
    onSend: () => void
    onReview?: () => void
    canSend: boolean
    reviewing?: boolean
    className?: string
}

export default function ChatComposer({
    value,
    onChange,
    onSend,
    onReview,
    canSend,
    reviewing,
    className
}: Props) {
    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            if (canSend) {
                onSend()
            }
        }
    }

    return (
        <div className={cn('border-t bg-background/95 backdrop-blur', className)}>
            <div className="mx-auto max-w-4xl p-4">
                <div className="flex flex-col gap-3">
                    <div className="relative">
                        <Textarea
                            placeholder="Ask about CI/CD, Kubernetes, Azure, Terraform..."
                            value={value}
                            onChange={(e) => onChange(e.target.value)}
                            onKeyDown={handleKeyDown}
                            rows={3}
                            className="min-h-[80px] resize-none pr-12 focus:ring-azure-500"
                        />
                        <Button
                            type="button"
                            onClick={onSend}
                            disabled={!canSend}
                            size="icon"
                            className="absolute bottom-2 right-2 h-8 w-8 bg-gradient-to-r from-azure-600 to-azure-700 hover:from-azure-700 hover:to-azure-800"
                        >
                            <Send className="h-4 w-4" />
                        </Button>
                    </div>

                    {onReview && (
                        <div className="flex gap-2">
                            <Button
                                type="button"
                                onClick={onReview}
                                variant="outline"
                                size="sm"
                                disabled={reviewing}
                                className="border-azure-200 hover:bg-azure-50"
                            >
                                {reviewing ? (
                                    <>
                                        <RotateCcw className="mr-2 h-4 w-4 animate-spin" />
                                        Reviewing...
                                    </>
                                ) : (
                                    <>
                                        <Sparkles className="mr-2 h-4 w-4" />
                                        Senior Review
                                    </>
                                )}
                            </Button>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}