import { logger } from './logger'

interface ToolsClientConfig {
    baseUrl: string
    authScheme?: 'bearer' | 'basic' | 'api-key'
    authToken?: string
    timeout?: number
    retries?: number
}

class ToolsClient {
    private config: ToolsClientConfig

    constructor(config: Partial<ToolsClientConfig> = {}) {
        this.config = {
            baseUrl: process.env.TOOL_BASE_URL || process.env.NEXT_PUBLIC_TOOL_BASE_URL || '',
            authScheme: (process.env.AUTH_SCHEME as any) || 'bearer',
            authToken: process.env.TOOL_AUTH_TOKEN,
            timeout: 20000,
            retries: 1,
            ...config
        }
    }

    private getHeaders(): Record<string, string> {
        const headers: Record<string, string> = { 'Content-Type': 'application/json' }
        if (this.config.authToken) {
            if (this.config.authScheme === 'bearer') headers.Authorization = `Bearer ${this.config.authToken}`
            else if (this.config.authScheme === 'api-key') headers['X-API-Key'] = this.config.authToken
            else if (this.config.authScheme === 'basic') headers.Authorization = `Basic ${this.config.authToken}`
        }
        return headers
    }

    private async fetchWithRetry(url: string, options: RequestInit): Promise<Response> {
        let lastError: any
        const maxRetries = this.config.retries || 1
        for (let attempt = 0; attempt <= maxRetries; attempt++) {
            try {
                const controller = new AbortController()
                const timeoutId = setTimeout(() => controller.abort(), this.config.timeout)
                const response = await fetch(url, { ...options, signal: controller.signal })
                clearTimeout(timeoutId)
                if (!response.ok && response.status >= 500 && attempt < maxRetries) {
                    logger.warn(`Request failed with ${response.status}, retrying...`, { attempt, url })
                    await new Promise(r => setTimeout(r, 1000 * Math.pow(2, attempt)))
                    continue
                }
                return response
            } catch (error: any) {
                lastError = error
                if (error.name === 'AbortError' && attempt < maxRetries) {
                    await new Promise(r => setTimeout(r, 1000 * Math.pow(2, attempt)))
                    continue
                }
                if (attempt < maxRetries) {
                    logger.warn('Request failed, retrying...', { attempt, url, error })
                    await new Promise(r => setTimeout(r, 1000 * Math.pow(2, attempt)))
                    continue
                }
            }
        }
        throw lastError || new Error('Request failed after retries')
    }

    async runTool(toolName: string, input: any): Promise<any> {
        if (!this.config.baseUrl) {
            logger.info('Running tool in mock mode', { toolName, input })
            return this.getMockResponse(toolName, input)
        }
        const url = `${this.config.baseUrl}/tools/${toolName}/run`
        try {
            const response = await this.fetchWithRetry(url, {
                method: 'POST',
                headers: this.getHeaders(),
                body: JSON.stringify(input)
            })
            if (!response.ok) {
                const error = await response.json().catch(() => ({ message: response.statusText }))
                throw new Error(error.message || `Tool execution failed: ${response.status}`)
            }
            return await response.json()
        } catch (error) {
            logger.error('Tool execution failed', { toolName, error })
            throw error
        }
    }

    private getMockResponse(toolName: string, input: any): any {
        const mockResponses: Record<string, any> = {
            deploy_azure: {
                deployment_id: `deploy-${Date.now()}`,
                status: 'success',
                resources: ['webapp', 'database', 'storage'],
                message: 'Deployment completed successfully'
            },
            kubernetes_deploy: {
                deployment_name: `k8s-deploy-${Date.now()}`,
                status: 'running',
                pods: [
                    { name: 'pod-1', status: 'running' },
                    { name: 'pod-2', status: 'running' }
                ]
            },
            terraform_plan: {
                plan_id: `plan-${Date.now()}`,
                changes: { add: 3, change: 1, destroy: 0 },
                summary: '3 resources to add, 1 to change, 0 to destroy'
            }
        }
        return mockResponses[toolName] || {
            status: 'success',
            message: `Mock response for ${toolName}`,
            timestamp: new Date().toISOString()
        }
    }
}

export const toolsClient = new ToolsClient()
