"use client"

import * as React from 'react'
import { cn } from '@/lib/utils'

type root_props = React.ComponentPropsWithoutRef<'div'>
type scrollbar_props = React.ComponentPropsWithoutRef<'div'> & {
    orientation?: 'vertical' | 'horizontal'
}

const ScrollArea = React.forwardRef<HTMLDivElement, root_props>(
    ({ className, children, ...props }, ref) => (
        <div
            ref={ref}
            className={cn('relative overflow-hidden', className)}
            {...props}
        >
            <div className="h-full w-full rounded-[inherit] overflow-auto">
                {children}
            </div>
            <ScrollBar />
        </div>
    ),
)
ScrollArea.displayName = 'ScrollArea'

const ScrollBar = React.forwardRef<HTMLDivElement, scrollbar_props>(
    ({ className, orientation = 'vertical', ...props }, ref) => (
        <div
            ref={ref}
            data-orientation={orientation}
            className={cn(
                'pointer-events-none absolute right-0 top-0 z-10 flex touch-none select-none transition-colors',
                orientation === 'vertical' &&
                'h-full w-2.5 border-l border-l-transparent p-[1px]',
                orientation === 'horizontal' &&
                'left-0 h-2.5 w-full flex-col border-t border-t-transparent p-[1px]',
                className,
            )}
            {...props}
        >
            <div className="relative flex-1 rounded-full bg-border" />
        </div>
    ),
)
ScrollBar.displayName = 'ScrollBar'

export { ScrollArea, ScrollBar }
