export function uuidv4(): string {
    const c: any = globalThis.crypto
    if (c && typeof c.randomUUID === 'function') return c.randomUUID()
    const buf = new Uint8Array(16)
    if (c && typeof c.getRandomValues === 'function') c.getRandomValues(buf)
    else for (let i = 0; i < 16; i++) buf[i] = Math.floor(Math.random() * 256)
    buf[6] = (buf[6] & 0x0f) | 0x40
    buf[8] = (buf[8] & 0x3f) | 0x80
    const b = Array.from(buf, v => v.toString(16).padStart(2, '0'))
    return `${b[0]}${b[1]}${b[2]}${b[3]}-${b[4]}${b[5]}-${b[6]}${b[7]}-${b[8]}${b[9]}-${b[10]}${b[11]}${b[12]}${b[13]}${b[14]}${b[15]}`
}
