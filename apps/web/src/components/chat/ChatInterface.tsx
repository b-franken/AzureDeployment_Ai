"use client"

import { useState, useRef, useEffect, useMemo } from "react"
import { Send, ArrowLeft, Copy, Check, User, Bot, GripVertical } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import LLMSelector from "@/components/chat/LLMSelector"
import { ReviewButton } from "@/components/chat/ReviewButton"
import { DeployButton } from "@/components/chat/DeployButton"
import { chat as call_chat, API_BASE_URL } from "@/lib/api"
import { chatStream } from "@/lib/stream"
import { ChatWSClient } from "@/lib/ws"

type ChatMsg = {
    id: string
    role: "user" | "assistant"
    content: string
    timestamp: Date
}

type ChatInterfaceProps = { onBack: () => void }

function splitModel(id: string): { provider: string | null; model: string | null } {
    if (!id) return { provider: null, model: null }
    const i = id.indexOf(":")
    if (i === -1) return { provider: null, model: id }
    return { provider: id.slice(0, i), model: id.slice(i + 1) }
}

export default function ChatInterface({ onBack }: ChatInterfaceProps) {
    const [messages, setMessages] = useState<ChatMsg[]>([])
    const [input, setInput] = useState("")
    const [isLoading, setIsLoading] = useState(false)
    const [copiedId, setCopiedId] = useState<string | null>(null)
    const [modelId, setModelId] = useState("openai:gpt-4o-mini")
    const [chatHeight, setChatHeight] = useState(500)
    const [isResizing, setIsResizing] = useState(false)
    const [deployToolsEnabled, setDeployToolsEnabled] = useState(false)
    const scrollRef = useRef<HTMLDivElement>(null)
    const inputRef = useRef<HTMLTextAreaElement>(null)
    const abortControllerRef = useRef<AbortController | null>(null)

    const transport = useMemo<"sse" | "ws">(
        () => (process.env.NEXT_PUBLIC_CHAT_TRANSPORT || "sse").toLowerCase() === "ws" ? "ws" : "sse",
        []
    )

    const wsRef = useRef<ChatWSClient | null>(null)

    useEffect(() => {
        scrollRef.current?.scrollIntoView({ behavior: "smooth" })
    }, [messages])

    useEffect(() => {
        const handleMouseMove = (e: MouseEvent) => {
            if (!isResizing) return
            const next = Math.min(Math.max(300, chatHeight + e.movementY), 800)
            setChatHeight(next)
        }
        const handleMouseUp = () => setIsResizing(false)
        if (isResizing) {
            document.addEventListener("mousemove", handleMouseMove)
            document.addEventListener("mouseup", handleMouseUp)
        }
        return () => {
            document.removeEventListener("mousemove", handleMouseMove)
            document.removeEventListener("mouseup", handleMouseUp)
        }
    }, [isResizing, chatHeight])

    useEffect(() => {
        if (transport !== "ws") return
        const client = new ChatWSClient({ url: API_BASE_URL })
        client.connect()
        wsRef.current = client
        return () => {
            wsRef.current?.close()
            wsRef.current = null
        }
    }, [transport])

    const handleSend = async () => {
        if (!input.trim() || isLoading) return

        if (abortControllerRef.current) abortControllerRef.current.abort()

        const now = new Date()
        const userMessage: ChatMsg = { id: crypto.randomUUID(), role: "user", content: input, timestamp: now }
        setMessages((prev) => [...prev, userMessage])
        setInput("")
        setIsLoading(true)

        try {
            const history = [...messages, userMessage].map((m) => ({ role: m.role, content: m.content }))
            const { provider, model } = splitModel(modelId)

            const assistantId = crypto.randomUUID()
            const assistantMsg: ChatMsg = { id: assistantId, role: "assistant", content: "", timestamp: new Date() }
            setMessages((prev) => [...prev, assistantMsg])

            if (!deployToolsEnabled) {
                if (transport === "ws" && wsRef.current) {
                    await new Promise<void>((resolve, reject) => {
                        try {
                            wsRef.current!.sendChat(
                                { input: userMessage.content, memory: history.slice(0, -1), provider, model },
                                {
                                    onDelta: (delta) => {
                                        setMessages((prev) =>
                                            prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + delta } : m))
                                        )
                                    },
                                    onDone: () => {
                                        setMessages((prev) =>
                                            prev.map((m) => (m.id === assistantId ? { ...m, timestamp: new Date() } : m))
                                        )
                                        resolve()
                                    },
                                    onError: (e) => reject(e instanceof Error ? e : new Error("ws_error")),
                                }
                            )
                        } catch (e) {
                            reject(e as Error)
                        }
                    }).catch(async () => {
                        abortControllerRef.current = new AbortController()
                        const fullContent = await chatStream(
                            API_BASE_URL,
                            { input: userMessage.content, memory: history.slice(0, -1), provider, model, enable_tools: false },
                            (delta) => {
                                setMessages((prev) =>
                                    prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + delta } : m))
                                )
                            },
                            abortControllerRef.current.signal
                        )
                        setMessages((prev) =>
                            prev.map((m) => (m.id === assistantId ? { ...m, content: fullContent, timestamp: new Date() } : m))
                        )
                    })
                } else {
                    abortControllerRef.current = new AbortController()
                    const fullContent = await chatStream(
                        API_BASE_URL,
                        { input: userMessage.content, memory: history.slice(0, -1), provider, model, enable_tools: false },
                        (delta) => {
                            setMessages((prev) =>
                                prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + delta } : m))
                            )
                        },
                        abortControllerRef.current.signal
                    )
                    setMessages((prev) =>
                        prev.map((m) => (m.id === assistantId ? { ...m, content: fullContent, timestamp: new Date() } : m))
                    )
                }
            } else {
                const reply = await call_chat(userMessage.content, history.slice(0, -1), provider, model, true)
                setMessages((prev) =>
                    prev.map((m) => (m.id === assistantId ? { ...m, content: reply, timestamp: new Date() } : m))
                )
            }
        } catch {
            setMessages((prev) => prev.slice(0, -1))
        } finally {
            setIsLoading(false)
            inputRef.current?.focus()
            abortControllerRef.current = null
        }
    }

    const handleCopy = (content: string, id: string) => {
        navigator.clipboard.writeText(content)
        setCopiedId(id)
        setTimeout(() => setCopiedId(null), 2000)
    }

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            handleSend()
        }
    }

    const lastUserMsg = messages.filter((m) => m.role === "user").slice(-1)[0]?.content ?? ""

    const handleReviewComplete = (text: string) => {
        const reviewMessage: ChatMsg = { id: crypto.randomUUID(), role: "assistant", content: `Review:\n${text}`, timestamp: new Date() }
        setMessages((prev) => [...prev, reviewMessage])
    }

    return (
        <div className="relative mx-auto max-w-5xl">
            <div className="glass overflow-hidden rounded-2xl shadow-2xl">
                <div className="flex items-center justify-between border-b border-white/10 p-4">
                    <div className="flex items-center gap-3">
                        <Button variant="ghost" size="icon" onClick={onBack} className="glass-hover">
                            <ArrowLeft className="h-5 w-5" />
                        </Button>
                        <div className="flex items-center gap-2">
                            <div className="h-2 w-2 animate-pulse rounded-full bg-green-500" />
                            <span className="text-sm text-muted-foreground">AI Assistant Online</span>
                        </div>
                    </div>
                    <div className="flex items-center gap-3">
                        <LLMSelector value={modelId} onChange={setModelId} />
                        <div className="hidden sm:flex items-center gap-3">
                            <DeployButton enabled={deployToolsEnabled} onToggle={setDeployToolsEnabled} />
                            <ReviewButton
                                getPayload={() => ({ chatId: "main", message: lastUserMsg || input, model: modelId })}
                                onComplete={handleReviewComplete}
                            />
                        </div>
                    </div>
                </div>

                <ScrollArea className="p-4" style={{ height: `${chatHeight}px` }}>
                    <div className="space-y-4">
                        {messages.map((message) => (
                            <div key={message.id} className={cn("flex gap-3", message.role === "user" ? "justify-end" : "justify-start")}>
                                {message.role === "assistant" && (
                                    <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-cyan-500">
                                        <Bot className="h-4 w-4 text-white" />
                                    </div>
                                )}
                                <div
                                    className={cn(
                                        "relative max-w-[80%] rounded-xl px-4 py-3 group",
                                        message.role === "user" ? "border border-blue-500/30 bg-gradient-to-r from-blue-500/20 to-cyan-500/20" : "glass"
                                    )}
                                >
                                    <p className="whitespace-pre-wrap text-sm">{message.content}</p>
                                    <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
                                        <span>{message.timestamp.toLocaleTimeString()}</span>
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            className="h-6 w-6 opacity-0 transition-opacity group-hover:opacity-100"
                                            onClick={() => handleCopy(message.content, message.id)}
                                        >
                                            {copiedId === message.id ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                                        </Button>
                                    </div>
                                </div>
                                {message.role === "user" && (
                                    <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-purple-500 to-pink-500">
                                        <User className="h-4 w-4 text-white" />
                                    </div>
                                )}
                            </div>
                        ))}
                        {isLoading && messages[messages.length - 1]?.content === "" && (
                            <div className="flex gap-3">
                                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-cyan-500">
                                    <Bot className="h-4 w-4 text-white" />
                                </div>
                                <div className="glass rounded-xl px-4 py-3">
                                    <div className="flex gap-1">
                                        <div className="h-2 w-2 animate-bounce rounded-full bg-blue-400" />
                                        <div className="animation-delay-200 h-2 w-2 animate-bounce rounded-full bg-blue-400" />
                                        <div className="animation-delay-400 h-2 w-2 animate-bounce rounded-full bg-blue-400" />
                                    </div>
                                </div>
                            </div>
                        )}
                        <div ref={scrollRef} />
                    </div>
                </ScrollArea>

                <div
                    className="flex h-2 cursor-row-resize items-center justify-center border-y border-white/10 hover:bg-white/5"
                    onMouseDown={() => setIsResizing(true)}
                >
                    <GripVertical className="h-4 w-4 text-muted-foreground" />
                </div>

                <div className="border-t border-white/10 p-4">
                    <div className="flex gap-2">
                        <textarea
                            ref={inputRef}
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder="Ask about Kubernetes, Docker, CI/CD, Terraform, cloud architecture..."
                            className="glass min-h-[60px] max-h-[120px] flex-1 resize-none rounded-xl border-0 p-3 text-sm outline-none focus:ring-2 focus:ring-blue-500/50"
                            disabled={isLoading}
                        />
                        <Button
                            onClick={handleSend}
                            disabled={!input.trim() || isLoading}
                            className="button-glow bg-gradient-to-r from-blue-500 to-cyan-500 hover:from-blue-600 hover:to-cyan-600"
                        >
                            <Send className="h-5 w-5" />
                        </Button>
                    </div>
                    <div className="mt-3 flex items-center gap-4">
                        <span className="text-xs text-muted-foreground">
                            {deployToolsEnabled && "Deploy tools enabled • "}Press Enter to send, Shift+Enter for new line
                        </span>
                    </div>
                </div>
            </div>
        </div>
    )
}
