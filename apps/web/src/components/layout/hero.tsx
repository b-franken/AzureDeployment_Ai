"use client"

import { ArrowRight } from "lucide-react"
import { Button } from "@/components/ui/button"

interface HeroProps {
    onStartChat: () => void
}

export default function Hero({ onStartChat }: HeroProps) {
    return (
        <section className="relative py-32 lg:py-40">
            <div className="absolute top-20 left-10 h-72 w-72 bg-blue-500/20 rounded-full blur-3xl animate-pulse-slow" />
            <div className="absolute bottom-20 right-10 h-96 w-96 bg-cyan-500/20 rounded-full blur-3xl animate-pulse-slow animation-delay-2000" />

            <div className="relative max-w-5xl mx-auto text-center">
                <h1 className="text-5xl lg:text-7xl font-bold tracking-tight mb-6">
                    <span className="block">Intelligent DevOps</span>
                    <span className="text-gradient">at Your Command</span>
                </h1>

                <p className="text-xl text-muted-foreground max-w-3xl mx-auto mb-12 leading-relaxed">
                    Transform your infrastructure operations with AI-powered insights.
                    Automate deployments, optimize CI/CD pipelines, and resolve issues faster
                    than ever before with intelligent assistance.
                </p>

                <div className="flex flex-col sm:flex-row gap-4 justify-center">
                    <Button
                        size="lg"
                        onClick={onStartChat}
                        className="bg-gradient-to-r from-blue-500 to-cyan-500 hover:from-blue-600 hover:to-cyan-600 text-lg px-8 py-6 button-glow group"
                    >
                        Start Conversation
                        <ArrowRight className="ml-2 h-5 w-5 group-hover:translate-x-1 transition-transform" />
                    </Button>
                </div>
            </div>
        </section>
    )
}
