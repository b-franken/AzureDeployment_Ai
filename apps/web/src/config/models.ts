export interface LLMModel {
    id: string
    displayName: string
    provider: string
    maxTokens?: number
    contextWindow?: number
    description?: string
}

export const AVAILABLE_LLM_MODELS: LLMModel[] = [

    {
        id: 'openai:gpt-4o-mini',
        displayName: 'GPT-4o Mini',
        provider: 'OpenAI',
        maxTokens: 16384,
        contextWindow: 128000,
        description: 'Fast and cost-effective model for most tasks'
    },
    {
        id: 'openai:gpt-4o',
        displayName: 'GPT-4o',
        provider: 'OpenAI',
        maxTokens: 4096,
        contextWindow: 128000,
        description: 'Most capable GPT-4 model, optimized for chat'
    },
    {
        id: 'openai:gpt-4',
        displayName: 'GPT-4',
        provider: 'OpenAI',
        maxTokens: 8192,
        contextWindow: 8192,
        description: 'Original GPT-4 model'
    },


    {
        id: 'anthropic:claude-3-5-sonnet',
        displayName: 'Claude 3.5 Sonnet',
        provider: 'Anthropic',
        maxTokens: 4096,
        contextWindow: 200000,
        description: 'Most intelligent Claude model'
    },
    {
        id: 'anthropic:claude-3-opus',
        displayName: 'Claude 3 Opus',
        provider: 'Anthropic',
        maxTokens: 4096,
        contextWindow: 200000,
        description: 'Powerful model for complex tasks'
    },

    {
        id: 'google:gemini-1.5-pro',
        displayName: 'Gemini 1.5 Pro',
        provider: 'Google',
        maxTokens: 8192,
        contextWindow: 1000000,
        description: 'Google\'s most capable model with huge context'
    },
    {
        id: 'google:gemini-1.5-flash',
        displayName: 'Gemini 1.5 Flash',
        provider: 'Google',
        maxTokens: 8192,
        contextWindow: 1000000,
        description: 'Fast and efficient Gemini model'
    },

    {
        id: 'factory:gpt-4o',
        displayName: 'GPT-4o Proxy',
        provider: 'Factory',
        maxTokens: 4096,
        contextWindow: 128000,
        description: 'Factory-hosted GPT-4o'
    },
    {
        id: 'factory:mixtral-8x7b',
        displayName: 'Mixtral 8x7B',
        provider: 'Factory',
        maxTokens: 32768,
        contextWindow: 32768,
        description: 'Open-source MoE model'
    },


    {
        id: 'ollama:llama3.1:8b',
        displayName: 'Llama 3.1 8B',
        provider: 'Ollama',
        description: 'Locally hosted Llama model'
    },
    {
        id: 'ollama:llama3.1:70b',
        displayName: 'Llama 3.1 70B',
        provider: 'Ollama',
        description: 'Large locally hosted Llama model'
    },
    {
        id: 'ollama:phi3:mini',
        displayName: 'Phi-3 Mini',
        provider: 'Ollama',
        description: 'Small efficient local model'
    }
]

export function getModelById(id: string): LLMModel | undefined {
    return AVAILABLE_LLM_MODELS.find(model => model.id === id)
}

export function getModelsByProvider(provider: string): LLMModel[] {
    return AVAILABLE_LLM_MODELS.filter(model => model.provider === provider)
}