import * as React from 'react'
import { cn } from '@/lib/utils'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Loader2 } from 'lucide-react'

type Message = {
    content: string
    [key: string]: any
}

export type ChatMsg = Message

const ChatMessage: React.FC<{ message: Message }> = ({ message }) => {
    return (
        <div className="px-4 py-2 text-sm text-foreground">
            {message.content}
        </div>
    )
}

interface Props {
    messages: ChatMsg[]
    busy?: boolean
    className?: string
}

export default function ChatMessages({ messages, busy, className }: Props) {
    const scrollRef = React.useRef<HTMLDivElement>(null)

    React.useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollIntoView({ behavior: 'smooth' })
        }
    }, [messages, busy])

    return (
        <ScrollArea className={cn('flex-1', className)}>
            <div className="flex flex-col">
                {messages.map((message, index) => (
                    <ChatMessage key={index} message={message} />
                ))}

                {busy && (
                    <div className="flex gap-3 px-4 py-6">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-azure-600 to-azure-700">
                            <Loader2 className="h-4 w-4 animate-spin text-white" />
                        </div>
                        <div className="flex items-center text-sm text-muted-foreground">
                            DevOps AI is thinking...
                        </div>
                    </div>
                )}

                <div ref={scrollRef} />
            </div>
        </ScrollArea>
    )
}