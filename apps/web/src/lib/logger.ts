type LogLevel = 'debug' | 'info' | 'warn' | 'error'

interface LogContext {
    [key: string]: any
}

class Logger {
    private isDevelopment = process.env.NODE_ENV === 'development'

    private log(level: LogLevel, message: string, context?: LogContext) {
        const timestamp = new Date().toISOString()
        const logEntry = {
            timestamp,
            level,
            message,
            ...context
        }

        if (this.isDevelopment || level === 'error') {
            const logMethod = level === 'error' ? console.error :
                level === 'warn' ? console.warn :
                    console.log

            logMethod(`[${timestamp}] [${level.toUpperCase()}] ${message}`, context || '')
        }


        if (!this.isDevelopment && typeof window === 'undefined') {

            this.sendToLoggingService(logEntry)
        }
    }

    private sendToLoggingService(logEntry: any) {

    }

    debug(message: string, context?: LogContext) {
        this.log('debug', message, context)
    }

    info(message: string, context?: LogContext) {
        this.log('info', message, context)
    }

    warn(message: string, context?: LogContext) {
        this.log('warn', message, context)
    }

    error(message: string, context?: LogContext) {
        this.log('error', message, context)
    }
}


class Tracer {
    startSpan(name: string) {
        const startTime = Date.now()
        return {
            setStatus(status: { code: number; message?: string }) {
                if (status.code !== 0) {
                    logger.warn(`Span ${name} failed`, { status })
                }
            },
            end() {
                const duration = Date.now() - startTime
                logger.debug(`Span ${name} completed`, { duration })
            }
        }
    }
}

export const logger = new Logger()
export const tracer = new Tracer()