export interface FormField {
    name: string
    label: string
    type: 'text' | 'number' | 'boolean' | 'select' | 'textarea' | 'object' | 'array'
    required?: boolean
    placeholder?: string
    description?: string
    min?: number
    max?: number
    options?: Array<{ label: string; value: string }>
}

export function schemaToFormFields(schema: any): FormField[] {
    if (!schema || !schema.properties) {
        return []
    }

    const fields: FormField[] = []
    const required = new Set(schema.required || [])

    type PropertySchema = {
        type?: 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array'
        title?: string
        description?: string
        placeholder?: string
        example?: string
        format?: string
        maxLength?: number
        minimum?: number
        maximum?: number
        enum?: any[]
    }

    for (const [name, property] of Object.entries(schema.properties as Record<string, PropertySchema>)) {
        const field: FormField = {
            name,
            label: property.title || name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
            type: 'text',
            required: required.has(name),
            description: property.description,
            placeholder: property.placeholder || property.example
        }

        if (property.type === 'string') {
            field.type = 'text'
            if (property.format === 'email') {
                field.type = 'text' // Could be 'email' in HTML, but kept as 'text' for simplicity
            } else if (property.maxLength && property.maxLength > 100) {
                field.type = 'textarea'
            }
        } else if (property.type === 'boolean') {
            field.type = 'boolean'
        } else if (property.type === 'number' || property.type === 'integer') {
            field.type = 'number'
            field.min = property.minimum
            field.max = property.maximum
        } else if (property.type === 'object') {
            field.type = 'object'
            field.placeholder = 'Enter valid JSON object'
        } else if (property.type === 'array') {
            field.type = 'array'
            field.placeholder = 'Enter valid JSON array'
        } else if (property.enum) {
            field.type = 'select'
            field.options = property.enum.map((value: any) => ({
                label: String(value),
                value: String(value)
            }))
        }
        if (property.type === 'boolean') {
            field.type = 'boolean'
        } else if (property.type === 'number' || property.type === 'integer') {
            field.type = 'number'
            field.min = property.minimum
            field.max = property.maximum
        } else if (property.type === 'object') {
            field.type = 'object'
            field.placeholder = 'Enter valid JSON object'
        } else if (property.type === 'array') {
            field.type = 'array'
            field.placeholder = 'Enter valid JSON array'
        } else if (property.enum) {
            field.type = 'select'
            field.options = property.enum.map((value: any) => ({
                label: String(value),
                value: String(value)
            }))
        } else if (property.maxLength && property.maxLength > 100) {
            field.type = 'textarea'
        }

        fields.push(field)
    }

    return fields
}