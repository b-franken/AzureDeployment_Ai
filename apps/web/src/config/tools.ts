import { z } from 'zod'

export interface Tool {
    name: string
    title: string
    description: string
    input_schema: any
    output_schema: any
}


const toolsManifest: Tool[] = [
    {
        name: 'deploy_azure',
        title: 'Azure Deployment',
        description: 'Deploy resources to Azure using ARM templates or Azure CLI',
        input_schema: {
            type: 'object',
            properties: {
                resource_group: {
                    type: 'string',
                    title: 'Resource Group',
                    description: 'Azure resource group name'
                },
                template_url: {
                    type: 'string',
                    title: 'Template URL',
                    description: 'URL to ARM template'
                },
                parameters: {
                    type: 'object',
                    title: 'Parameters',
                    description: 'Template parameters as JSON'
                }
            },
            required: ['resource_group']
        },
        output_schema: {
            type: 'object',
            properties: {
                deployment_id: { type: 'string' },
                status: { type: 'string', enum: ['success', 'failed', 'pending'] },
                resources: { type: 'array', items: { type: 'string' } },
                message: { type: 'string' }
            }
        }
    },
    {
        name: 'kubernetes_deploy',
        title: 'Kubernetes Deployment',
        description: 'Deploy applications to Kubernetes cluster',
        input_schema: {
            type: 'object',
            properties: {
                namespace: {
                    type: 'string',
                    title: 'Namespace',
                    description: 'Kubernetes namespace'
                },
                manifest: {
                    type: 'string',
                    title: 'Manifest',
                    description: 'YAML manifest content'
                },
                replicas: {
                    type: 'number',
                    title: 'Replicas',
                    description: 'Number of replicas',
                    minimum: 1,
                    maximum: 10
                }
            },
            required: ['namespace', 'manifest']
        },
        output_schema: {
            type: 'object',
            properties: {
                deployment_name: { type: 'string' },
                status: { type: 'string' },
                pods: {
                    type: 'array',
                    items: {
                        type: 'object',
                        properties: {
                            name: { type: 'string' },
                            status: { type: 'string' }
                        }
                    }
                }
            }
        }
    },
    {
        name: 'terraform_plan',
        title: 'Terraform Plan',
        description: 'Generate and review Terraform execution plan',
        input_schema: {
            type: 'object',
            properties: {
                working_directory: {
                    type: 'string',
                    title: 'Working Directory',
                    description: 'Path to Terraform configuration'
                },
                variables: {
                    type: 'object',
                    title: 'Variables',
                    description: 'Terraform variables as JSON'
                },
                auto_approve: {
                    type: 'boolean',
                    title: 'Auto Approve',
                    description: 'Automatically approve the plan'
                }
            },
            required: ['working_directory']
        },
        output_schema: {
            type: 'object',
            properties: {
                plan_id: { type: 'string' },
                changes: {
                    type: 'object',
                    properties: {
                        add: { type: 'number' },
                        change: { type: 'number' },
                        destroy: { type: 'number' }
                    }
                },
                summary: { type: 'string' }
            }
        }
    }
]

export async function getToolsManifest(): Promise<Tool[]> {
    return toolsManifest
}

export async function getToolByName(name: string): Promise<Tool | undefined> {
    const tools = await getToolsManifest()
    return tools.find(tool => tool.name === name)
}

export function validateInput(schema: any, data: any): { valid: boolean; errors?: any[] } {
    try {
        const required = schema.required || []
        const errors: any[] = []

        for (const field of required) {
            if (!data[field]) {
                errors.push({
                    field,
                    message: `${field} is required`
                })
            }
        }

        if (errors.length > 0) {
            return { valid: false, errors }
        }

        return { valid: true }
    } catch (error) {
        return {
            valid: false,
            errors: [{ message: 'Validation failed', error }]
        }
    }
}