"use client"

import { Terminal, Github, Settings } from "lucide-react"
import { Button } from "@/components/ui/button"

export default function Header() {
    return (
        <header className="fixed top-0 left-0 right-0 z-50 glass border-b border-white/5">
            <div className="container mx-auto px-4">
                <div className="flex h-16 items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-cyan-500 shadow-lg shadow-blue-500/25">
                            <Terminal className="h-5 w-5 text-white" />
                        </div>
                        <div>
                            <h1 className="text-lg font-semibold text-foreground">DevOps AI</h1>
                        </div>
                    </div>

                    <div className="flex items-center gap-2">
                        <Button variant="ghost" size="icon" className="glass-hover" asChild>
                            <a
                                href="https://github.com/b-franken/DevOps_AI"
                                target="_blank"
                                rel="noopener noreferrer"
                                aria-label="Open GitHub repository"
                            >
                                <Github className="h-5 w-5" />
                            </a>
                        </Button>
                        <Button variant="ghost" size="icon" className="glass-hover">
                            <Settings className="h-5 w-5" />
                        </Button>
                    </div>
                </div>
            </div>
        </header>
    )
}
