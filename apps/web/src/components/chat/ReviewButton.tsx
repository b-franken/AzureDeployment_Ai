"use client"

import * as React from "react"
import { Button } from "@/components/ui/button"
import { chat, review_once } from "@/lib/api"

type Payload = { chatId: string; message: string; model: string }
type Props = {
    getPayload?: () => Payload
    message?: string
    model?: string
    onComplete?: (text: string) => void
}

function splitModel(id: string): { provider: string | null; model: string | null } {
    if (!id) return { provider: null, model: null }
    const i = id.indexOf(":")
    if (i === -1) return { provider: null, model: id }
    return { provider: id.slice(0, i), model: id.slice(i + 1) }
}

export function ReviewButton({ getPayload, message, model, onComplete }: Props) {
    const [busy, setBusy] = React.useState(false)

    const canRun = React.useMemo(() => {
        if (typeof getPayload === "function") return true
        return Boolean(message && model)
    }, [getPayload, message, model])

    async function onClick() {
        let p: Payload
        if (typeof getPayload === "function") p = getPayload()
        else p = { chatId: "default", message: message || "", model: model || "" }
        if (!p.message) return
        setBusy(true)
        try {
            const { provider, model } = splitModel(p.model)
            const ai = await chat(p.message, [], { provider, model })
            const out = await review_once(p.message, ai, { provider, model })
            if (onComplete) onComplete(out)
        } finally {
            setBusy(false)
        }
    }

    return (
        <Button onClick={onClick} disabled={busy || !canRun}>
            {busy ? "reviewing..." : "run reviewer"}
        </Button>
    )
}
