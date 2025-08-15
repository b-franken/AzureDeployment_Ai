import type { Metadata } from "next"
import { Inter } from "next/font/google"
import "./globals.css"

const inter = Inter({
    subsets: ["latin"],
    variable: "--font-inter"
})

export const metadata: Metadata = {
    title: "DevOps AI Assistant | Enterprise-Grade Infrastructure Intelligence",
    description: "Advanced AI-powered DevOps assistant for infrastructure automation, CI/CD optimization, and cloud architecture",
    keywords: "DevOps, AI, Infrastructure, Kubernetes, Docker, Terraform, Azure, AWS",
}

export default function RootLayout({
    children
}: {
    children: React.ReactNode
}) {
    return (
        <html lang="en" className="dark">
            <body className={`${inter.variable} font-sans antialiased`}>
                <div className="relative min-h-screen bg-gradient-to-br from-slate-950 via-blue-950/20 to-slate-950">
                    <div className="absolute inset-0 grid-pattern opacity-20" />
                    <div className="absolute inset-0 bg-gradient-to-t from-background via-background/95 to-transparent" />
                    {children}
                </div>
            </body>
        </html>
    )
}