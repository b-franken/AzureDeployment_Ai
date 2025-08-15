"use client"

import * as React from "react"
import { Switch } from "@/components/ui/switch"

type Props = {
    enabled: boolean
    onToggle: (enabled: boolean) => void
    className?: string
}

export function DeployButton({ enabled, onToggle, className }: Props) {
    return (
        <div className={`flex items-center gap-2 ${className ?? ""}`}>
            <span className="text-xs text-muted-foreground">Deploy</span>
            <div className="glass rounded-lg border border-white/10 px-3 py-1.5 shadow-sm">
                <Switch
                    id="deploy-tools"
                    checked={enabled}
                    onCheckedChange={onToggle}
                    className="data-[state=checked]:bg-gradient-to-r data-[state=checked]:from-blue-500 data-[state=checked]:to-cyan-500 data-[state=unchecked]:bg-white/20"
                />
            </div>
        </div>
    )
}