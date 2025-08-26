// src/lib/ws.ts
type ChatInit = {
    provider?: string | null;
    model?: string | null;
    memory?: Array<{ role: string; content: string }>;
    input?: string;
};

export type ChatSocket = {
    sendChat: (init: ChatInit) => void;
    ping: () => void;
    close: () => void;
};

function buildWsUrl(path = "/ws/chat"): string {
    const { protocol, host } = window.location;
    const wsProto = protocol === "https:" ? "wss:" : "ws:";
    return `${wsProto}//${host}${path}`;
}

export function connectChatWs(
    onDelta: (text: string) => void,
    opts?: {
        onOpen?: () => void;
        onDone?: () => void;
        onError?: (msg: string) => void;
        onFatal?: (why: string) => void;
        path?: string;
    },
): ChatSocket {
    const url = buildWsUrl(opts?.path ?? "/ws/chat");
    let attempt = 0;
    let ws: WebSocket | null = null;
    let closedByClient = false;

    const maxDelay = 5000;
    const backoff = () => Math.min(250 * 2 ** Math.max(0, attempt - 1), maxDelay);

    const open = () => {
        ws = new WebSocket(url, "json");
        ws.onopen = () => {
            attempt = 0;
            opts?.onOpen?.();
        };
        ws.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                switch (msg.type) {
                    case "delta":
                        if (typeof msg.data === "string") onDelta(msg.data);
                        break;
                    case "done":
                        opts?.onDone?.();
                        break;
                    case "error":
                        opts?.onError?.(String(msg.message ?? "error"));
                        break;
                    case "pong":
                    default:
                        break;
                }
            } catch { }
        };
        ws.onerror = () => { };
        ws.onclose = (ev) => {
            if (closedByClient) return;
            if (ev.code === 1000 || ev.code === 1001) return;
            if (ev.code === 1008) {
                opts?.onFatal?.("forbidden_or_bad_origin");
                return;
            }
            if (ev.code === 1006 || ev.code === 1011) {
                attempt += 1;
                setTimeout(open, backoff());
                return;
            }
            opts?.onFatal?.(`closed_${ev.code}`);
        };
    };

    open();

    return {
        sendChat(init: ChatInit) {
            if (!ws || ws.readyState !== WebSocket.OPEN) return;
            const payload = {
                type: "chat",
                provider: init.provider ?? undefined,
                model: init.model ?? undefined,
                memory: init.memory ?? [],
                input: init.input ?? "",
            };
            ws.send(JSON.stringify(payload));
        },
        ping() {
            if (!ws || ws.readyState !== WebSocket.OPEN) return;
            ws.send(JSON.stringify({ type: "ping" }));
        },
        close() {
            closedByClient = true;
            ws?.close(1000, "client_close");
        },
    };
}
