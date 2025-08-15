"use client"

import * as React from "react"
import { ReviewButton } from "@/components/chat/ReviewButton"
import { Button } from "@/components/ui/button"
import { chat as call_chat } from "@/lib/api"

type ReviewPayload = { chatId: string; message: string; model: string }
const ReviewButtonWithPayload = ReviewButton as unknown as React.ComponentType<{
    getPayload: () => ReviewPayload
}>

export default function ChatPage() {
    const [model] = React.useState("gpt-4o-mini")
    const [messages, setMessages] = React.useState<
        { role: "user" | "assistant"; content: string }[]
    >([])
    const [input, setInput] = React.useState("")
    const [busy, setBusy] = React.useState(false)

    async function sendMessage() {
        if (!input.trim() || busy) return
        const outgoing = { role: "user" as const, content: input }
        setMessages((m) => [...m, outgoing])
        setInput("")
        setBusy(true)
        try {
            const reply = await call_chat(outgoing.content, messages as any, {
                model,
            })
            setMessages((m) => [...m, { role: "assistant", content: reply }])
        } finally {
            setBusy(false)
        }
    }

    return (
        <div className="flex h-full flex-col gap-3">
            <div className="flex items-center justify-between">
                <ReviewButtonWithPayload
                    getPayload={() => ({
                        chatId: "default",
                        message:
                            messages.filter((m) => m.role === "user").slice(-1)[0]?.content ??
                            "",
                        model,
                    })}
                />
            </div>

            <div className="flex-1 overflow-y-auto rounded-xl border border-border bg-card p-4">
                {messages.length === 0 ? (
                    <div className="text-center text-sm text-muted-foreground">
                        Start a conversation
                    </div>
                ) : (
                    <div className="space-y-3">
                        {messages.map((m, i) => (
                            <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
                                <div className="inline-block max-w-[80%] rounded-xl border border-border bg-secondary px-3 py-2 text-sm">
                                    {m.content}
                                </div>
                            </div>
                        ))}
                        {busy && (
                            <div className="text-left">
                                <div className="inline-block max-w-[80%] rounded-xl border border-border bg-secondary px-3 py-2 text-sm">
                                    ...
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>

            <div className="flex items-center gap-2 rounded-xl border border-border bg-card p-2">
                <input
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="Type a message"
                    className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
                />
                <Button onClick={sendMessage} disabled={busy}>
                    Send
                </Button>
            </div>
        </div>
    )
}
