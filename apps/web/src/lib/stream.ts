import { API_BASE_URL } from "@/lib/api"

export async function chatStream(
    baseURL: string | null | undefined,
    body: {
        input: string
        memory?: { role: "user" | "assistant" | "system"; content: string }[]
        provider?: string | null
        model?: string | null
        enable_tools?: boolean
    },
    onDelta: (text: string) => void
): Promise<string> {
    const base = (baseURL && baseURL.trim() ? baseURL : API_BASE_URL).replace(/\/+$/, "")
    const url = `${base}/api/chat?stream=true`
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
    let buf = ""
    while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        let nl: number
        while ((nl = buf.indexOf("\n")) !== -1) {
            const raw = buf.slice(0, nl)
            buf = buf.slice(nl + 1)
            if (!raw.startsWith("data:")) continue
            let data = raw.slice(5)
            if (data.startsWith(" ")) data = data.slice(1)
            if (!data || data === "[DONE]") continue
            try {
                const obj = JSON.parse(data)
                const text = typeof obj === "string" ? obj : typeof obj.data === "string" ? obj.data : ""
                if (text) {
                    full += text
                    onDelta(text)
                }
            } catch {
                full += data
                onDelta(data)
            }
        }
    }
    return full
}
