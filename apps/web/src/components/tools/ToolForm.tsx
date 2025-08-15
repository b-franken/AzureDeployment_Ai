'use client'

import { useState } from 'react'
import { schemaToFormFields, FormField } from '@/lib/schema'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Play, RotateCcw } from 'lucide-react'

interface ToolFormProps {
    schema: any
    onSubmit: (data: any) => void
    isLoading?: boolean
}

function isEmptyValue(v: any) {
    if (v === null || v === undefined) return true
    if (typeof v === 'string' && v.trim() === '') return true
    return false
}

export default function ToolForm({ schema, onSubmit, isLoading }: ToolFormProps) {
    const fields = schemaToFormFields(schema)
    const [formData, setFormData] = useState<Record<string, any>>({})
    const [errors, setErrors] = useState<Record<string, string>>({})

    const handleChange = (name: string, value: any) => {
        setFormData(prev => ({ ...prev, [name]: value }))
        setErrors(prev => ({ ...prev, [name]: '' }))
    }

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault()
        const newErrors: Record<string, string> = {}
        const payload: Record<string, any> = { ...formData }

        for (const field of fields) {
            const value = payload[field.name]
            if (field.required && isEmptyValue(value)) {
                newErrors[field.name] = `${field.label} is required`
                continue
            }
            if (field.type === 'number' && value === '') {
                payload[field.name] = undefined
            }
            if ((field.type === 'object' || field.type === 'array') && typeof value === 'string' && value.trim() !== '') {
                try {
                    payload[field.name] = JSON.parse(value)
                } catch {
                    newErrors[field.name] = `Invalid JSON for ${field.label}`
                }
            }
        }

        if (Object.keys(newErrors).length > 0) {
            setErrors(newErrors)
            return
        }

        onSubmit(payload)
    }

    const handleReset = () => {
        setFormData({})
        setErrors({})
    }

    const renderField = (field: FormField) => {
        const value = formData[field.name] ?? (field.type === 'boolean' ? false : '')
        const error = errors[field.name]

        switch (field.type) {
            case 'text':
                return (
                    <div key={field.name} className="space-y-2">
                        <Label htmlFor={field.name}>
                            {field.label}
                            {field.required && <span className="text-destructive ml-1">*</span>}
                        </Label>
                        <Input
                            id={field.name}
                            type="text"
                            value={value}
                            onChange={(e) => handleChange(field.name, e.target.value)}
                            placeholder={field.placeholder}
                            className={error ? 'border-destructive' : ''}
                        />
                        {field.description && (
                            <p className="text-xs text-muted-foreground">{field.description}</p>
                        )}
                        {error && <p className="text-xs text-destructive">{error}</p>}
                    </div>
                )

            case 'number':
                return (
                    <div key={field.name} className="space-y-2">
                        <Label htmlFor={field.name}>
                            {field.label}
                            {field.required && <span className="text-destructive ml-1">*</span>}
                        </Label>
                        <Input
                            id={field.name}
                            type="number"
                            value={value}
                            onChange={(e) => {
                                const v = e.target.value
                                if (v === '') handleChange(field.name, '')
                                else handleChange(field.name, Number.isNaN(parseFloat(v)) ? '' : parseFloat(v))
                            }}
                            placeholder={field.placeholder}
                            min={field.min}
                            max={field.max}
                            className={error ? 'border-destructive' : ''}
                        />
                        {field.description && (
                            <p className="text-xs text-muted-foreground">{field.description}</p>
                        )}
                        {error && <p className="text-xs text-destructive">{error}</p>}
                    </div>
                )

            case 'boolean':
                return (
                    <div key={field.name} className="flex items-center justify-between space-y-2">
                        <div className="space-y-0.5">
                            <Label htmlFor={field.name}>
                                {field.label}
                                {field.required && <span className="text-destructive ml-1">*</span>}
                            </Label>
                            {field.description && (
                                <p className="text-xs text-muted-foreground">{field.description}</p>
                            )}
                        </div>
                        <Switch
                            id={field.name}
                            checked={Boolean(value)}
                            onCheckedChange={(checked) => handleChange(field.name, checked)}
                        />
                    </div>
                )

            case 'select':
                return (
                    <div key={field.name} className="space-y-2">
                        <Label htmlFor={field.name}>
                            {field.label}
                            {field.required && <span className="text-destructive ml-1">*</span>}
                        </Label>
                        <select
                            id={field.name}
                            value={value}
                            onChange={(e) => handleChange(field.name, e.target.value)}
                            className={`flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ${error ? 'border-destructive' : ''
                                }`}
                        >
                            <option value="">Select...</option>
                            {field.options?.map(option => (
                                <option key={option.value} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                        {field.description && (
                            <p className="text-xs text-muted-foreground">{field.description}</p>
                        )}
                        {error && <p className="text-xs text-destructive">{error}</p>}
                    </div>
                )

            case 'textarea':
                return (
                    <div key={field.name} className="space-y-2">
                        <Label htmlFor={field.name}>
                            {field.label}
                            {field.required && <span className="text-destructive ml-1">*</span>}
                        </Label>
                        <Textarea
                            id={field.name}
                            value={value}
                            onChange={(e) => handleChange(field.name, e.target.value)}
                            placeholder={field.placeholder}
                            rows={4}
                            className={error ? 'border-destructive' : ''}
                        />
                        {field.description && (
                            <p className="text-xs text-muted-foreground">{field.description}</p>
                        )}
                        {error && <p className="text-xs text-destructive">{error}</p>}
                    </div>
                )

            case 'object':
            case 'array':
                return (
                    <div key={field.name} className="space-y-2">
                        <Label htmlFor={field.name}>
                            {field.label}
                            {field.required && <span className="text-destructive ml-1">*</span>}
                        </Label>
                        <Textarea
                            id={field.name}
                            value={typeof value === 'string' ? value : JSON.stringify(value ?? '', null, 2)}
                            onChange={(e) => handleChange(field.name, e.target.value)}
                            placeholder={`Enter valid JSON for ${field.type}`}
                            rows={6}
                            className={`font-mono text-xs ${error ? 'border-destructive' : ''}`}
                        />
                        {field.description && (
                            <p className="text-xs text-muted-foreground">{field.description}</p>
                        )}
                        {error && <p className="text-xs text-destructive">{error}</p>}
                    </div>
                )

            default:
                return null
        }
    }

    return (
        <form onSubmit={handleSubmit} className="space-y-6">
            {fields.map(renderField)}
            <div className="flex gap-3">
                <Button type="submit" disabled={isLoading}>
                    {isLoading ? (
                        <>
                            <RotateCcw className="mr-2 h-4 w-4 animate-spin" />
                            Executing...
                        </>
                    ) : (
                        <>
                            <Play className="mr-2 h-4 w-4" />
                            Execute Tool
                        </>
                    )}
                </Button>
                <Button type="button" variant="outline" onClick={handleReset}>
                    Reset
                </Button>
            </div>
        </form>
    )
}
