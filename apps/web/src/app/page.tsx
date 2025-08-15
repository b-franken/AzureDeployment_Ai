"use client"

import { useState } from "react"
import ChatInterface from "@/components/chat/ChatInterface"
import Header from "@/components/layout/header"
import Hero from "@/components/layout/hero"


export default function Home() {
    const [showChat, setShowChat] = useState(false)

    return (
        <main className="relative">
            <Header />
            {!showChat ? (
                <div className="container mx-auto px-4">
                    <Hero onStartChat={() => setShowChat(true)} />
                </div>
            ) : (
                <div className="container mx-auto px-4 py-24">
                    <ChatInterface onBack={() => setShowChat(false)} />
                </div>
            )}
        </main>
    )
}
