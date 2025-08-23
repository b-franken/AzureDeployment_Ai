export async function chatStream(
    baseURL: string,
    body: {
        input: string
        memory?: { role: "user" | "assistant" | "system"; content: string }[]
        provider?: string | null
        model?: string | null
        enable_tools?: boolean
    },
    onDelta: (text: string) => void
): Promise<string> {
    const url = `${baseURL.replace(/\/+$/, "")}/api/chat?stream=true`
    const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    })
    if (!res.ok || !res.body) {
        const msg = await res.text().catch(() => "stream failed")
        throw new Error(msg || `HTTP ${res.status}`)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let full = ""
    while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split(/\r?\n/)
        for (const line of lines) {
            if (!line.startsWith("data:")) continue
            const data = line.slice(5).trim()
            if (!data) continue
            try {
                const obj = JSON.parse(data)
                if (typeof obj === "string") {
                    full += obj
                    onDelta(obj)
                } else if (typeof obj.data === "string") {
                    full += obj.data
                    onDelta(obj.data)
                }
            } catch {
                full += data
                onDelta(data)
            }
        }
    }
    return full
}
