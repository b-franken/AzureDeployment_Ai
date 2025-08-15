import * as React from 'react'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Button } from '@/components/ui/button'
import { Settings, Github, FileText } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
    enableTools: boolean
    onToggle: (v: boolean) => void
    title?: string
    className?: string
}

export default function ChatTopbar({
    enableTools,
    onToggle,
    title = 'DevOps AI Assistant',
    className
}: Props) {
    return (
        <div className={cn('border-b bg-background/95 backdrop-blur', className)}>
            <div className="flex h-16 items-center justify-between px-4">
                <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-azure-600 to-azure-700">
                        <FileText className="h-5 w-5 text-white" />
                    </div>
                    <div>
                        <h1 className="text-lg font-semibold">{title}</h1>
                        <p className="text-xs text-muted-foreground">
                            Powered by Azure AI
                        </p>
                    </div>
                </div>

                <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2">
                        <Label htmlFor="tools" className="text-sm">
                            Enable Tools
                        </Label>
                        <Switch
                            id="tools"
                            checked={enableTools}
                            onCheckedChange={onToggle}
                            className="data-[state=checked]:bg-azure-600"
                        />
                    </div>

                    <div className="flex items-center gap-2">
                        <Button variant="ghost" size="icon">
                            <Github className="h-5 w-5" />
                        </Button>
                        <Button variant="ghost" size="icon">
                            <Settings className="h-5 w-5" />
                        </Button>
                    </div>
                </div>
            </div>
        </div>
    )
}