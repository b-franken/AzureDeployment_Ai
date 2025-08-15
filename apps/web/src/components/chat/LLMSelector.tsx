"use client"

import * as React from "react"

type ModelOption = { id: string; label: string }

type Props = {
    value: string
    onChange: (value: string) => void
    options?: ModelOption[]
    className?: string
}

const DEFAULT_OPTIONS: ModelOption[] = [
    { id: "openai:gpt-5.5-preview", label: "OpenAI • GPT-5.5 Preview" },
    { id: "openai:gpt-5", label: "OpenAI • GPT-5" },
    { id: "openai:gpt-4o", label: "OpenAI • GPT-4o" },
    { id: "openai:gpt-4o-mini", label: "OpenAI • GPT-4o Mini" },

    { id: "google:gemini-1.5-pro", label: "Google • Gemini 1.5 Pro" },
    { id: "google:gemini-1.5-flash", label: "Google • Gemini 1.5 Flash" },

    { id: "ollama:llama3.1", label: "Ollama • Llama 3.1" },
    { id: "ollama:mistral", label: "Ollama • Mistral" },
    { id: "ollama:gemma", label: "Ollama • Gemma" },
]

export default function LLMSelector({ value, onChange, options = DEFAULT_OPTIONS, className }: Props) {
    return (
        <div className={`inline-flex items-center gap-2 ${className ?? ""}`}>
            <span className="text-xs text-muted-foreground">Model</span>
            <div className="glass rounded-lg border border-white/10 shadow-sm">
                <select
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    className="h-9 bg-transparent px-3 pr-8 text-sm text-foreground outline-none appearance-none"
                >
                    {options.map((o) => (
                        <option key={o.id} value={o.id}>
                            {o.label}
                        </option>
                    ))}
                </select>
            </div>
        </div>
    )
}
