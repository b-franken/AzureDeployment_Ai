export type ChatMemoryItem = { role: "user" | "assistant" | "system"; content: string };
export type ChatInit = { provider?: string; model?: string; memory?: ChatMemoryItem[]; input: string };

export type ChatEvents = {
    onDelta?: (chunk: string) => void;
    onDone?: () => void;
    onError?: (message: string) => void;
    onOpen?: () => void;
    onClose?: (code: number) => void;
};

export type ChatWSOptions = {
    url?: string;
    pingIntervalMs?: number;
    maxReconnectAttempts?: number;
    reconnect?: boolean;
} & ChatEvents;

export class ChatWSClient {
    private url: string;
    private ws: WebSocket | null = null;
    private pingInterval: number | null = null;
    private attempt = 0;
    private readonly pingIntervalMs: number;
    private reconnect: boolean;
    private readonly maxReconnectAttempts: number;
    private readonly ev: ChatEvents;

    constructor(opts: ChatWSOptions = {}) {
        const scheme = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss" : "ws";
        const host = typeof window !== "undefined" ? window.location.host : "localhost:8000";
        this.url = opts.url ?? `${scheme}://${host}/ws/chat`;
        this.pingIntervalMs = opts.pingIntervalMs ?? 25000;
        this.reconnect = opts.reconnect ?? true;
        this.maxReconnectAttempts = opts.maxReconnectAttempts ?? 5;
        this.ev = opts;
    }

    connect() {
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
        this.ws = new WebSocket(this.url, "json");
        this.ws.onopen = () => {
            this.startHeartbeat();
            this.attempt = 0;
            this.ev.onOpen?.();
        };
        this.ws.onmessage = (evt) => {
            const msg = safeParse(evt.data);
            const t = msg?.type ?? "delta";
            if (t === "delta") this.ev.onDelta?.(String(msg?.data ?? ""));
            else if (t === "done") this.ev.onDone?.();
            else if (t === "error") this.ev.onError?.(String(msg?.message ?? "error"));
        };
        this.ws.onclose = (e) => {
            this.stopHeartbeat();
            this.ev.onClose?.(e.code);
            if (!this.reconnect) return;
            if (this.attempt >= this.maxReconnectAttempts) return;
            this.attempt += 1;
            const backoff = Math.min(1000 * 2 ** (this.attempt - 1), 8000) + Math.floor(Math.random() * 200);
            setTimeout(() => this.connect(), backoff);
        };
        this.ws.onerror = () => {
            this.ev.onError?.("ws_error");
        };
    }

    sendChat(init: ChatInit) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) throw new Error("ws_not_open");
        const payload = { type: "chat", init };
        this.ws.send(JSON.stringify(payload));
    }

    close(code = 1000, reason = "client_close") {
        this.stopHeartbeat();
        this.reconnect = false;
        this.ws?.close(code, reason);
        this.ws = null;
    }

    private startHeartbeat() {
        this.stopHeartbeat();
        this.pingInterval = window.setInterval(() => {
            try {
                this.ws?.send(JSON.stringify({ type: "ping" }));
            } catch {
                /* no-op */
            }
        }, this.pingIntervalMs);
    }

    private stopHeartbeat() {
        if (this.pingInterval) window.clearInterval(this.pingInterval);
        this.pingInterval = null;
    }
}

function safeParse(data: unknown): any {
    try {
        if (typeof data === "string") return JSON.parse(data);
        return data;
    } catch {
        return null;
    }
}
