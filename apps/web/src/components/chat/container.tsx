import * as React from 'react'
import { cn } from '@/lib/utils'

interface Props extends React.PropsWithChildren {
    className?: string
}

export default function ChatContainer({ className, children }: Props) {
    return (
        <div className={cn('flex h-screen flex-col bg-background', className)}>
            {children}
        </div>
    )
}