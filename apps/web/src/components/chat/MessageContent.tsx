// MessageContent.tsx
import React from 'react'
import { Copy, Check } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface MessageContentProps {
  content: string
  onCopy?: (text: string) => void
}

interface CodeBlockProps {
  language: string
  code: string
  onCopy?: (text: string) => void
}

const CodeBlock: React.FC<CodeBlockProps> = ({ language, code, onCopy }) => {
  const [copied, setCopied] = React.useState(false)

  const handleCopy = () => {
    if (onCopy) {
      onCopy(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const getLanguageColor = (lang: string) => {
    switch (lang.toLowerCase()) {
      case 'bicep':
        return 'bg-blue-500/10 border-blue-500/30 text-blue-300'
      case 'terraform':
      case 'hcl':
        return 'bg-purple-500/10 border-purple-500/30 text-purple-300'
      case 'json':
        return 'bg-green-500/10 border-green-500/30 text-green-300'
      case 'yaml':
      case 'yml':
        return 'bg-orange-500/10 border-orange-500/30 text-orange-300'
      default:
        return 'bg-gray-500/10 border-gray-500/30 text-gray-300'
    }
  }

  return (
    <div className="my-4 rounded-lg border border-white/20 bg-black/80 overflow-hidden shadow-lg">
      <div className="flex items-center justify-between px-4 py-2 bg-black/90 border-b border-white/20">
        <span
          className="text-xs font-semibold px-2 py-1 rounded border border-white/30 text-white"
        >
          {language.toUpperCase()}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleCopy}
          className="h-6 text-xs text-white hover:text-gray-200 transition-colors"
        >
          {copied ? <Check className="w-3 h-3 mr-1" /> : <Copy className="w-3 h-3 mr-1" />}
          {copied ? 'Copied!' : 'Copy'}
        </Button>
      </div>
      <div className="p-4 overflow-x-auto bg-black/70">
        <pre className="text-sm leading-relaxed font-mono">
          <code className="text-white">{code}</code>
        </pre>
      </div>
    </div>
  )
}

const MessageContent: React.FC<MessageContentProps> = ({ content, onCopy }) => {
  const parseContent = (text: string) => {
    const parts: { type: string; content: string; language?: string }[] = []
    let currentIndex = 0

    const codeBlockRegex = /```(\w+)?\n([\s\S]*?)```/g
    let match

    while ((match = codeBlockRegex.exec(text)) !== null) {
      if (match.index > currentIndex) {
        const textBefore = text.slice(currentIndex, match.index)
        if (textBefore.trim()) {
          parts.push({ type: 'text', content: textBefore })
        }
      }
      const language = match[1] || 'text'
      const code = match[2].trim()
      parts.push({ type: 'code', language, content: code })
      currentIndex = match.index + match[0].length
    }

    if (currentIndex < text.length) {
      const remainingText = text.slice(currentIndex)
      if (remainingText.trim()) {
        parts.push({ type: 'text', content: remainingText })
      }
    }

    return parts.length > 0 ? parts : [{ type: 'text', content: text }]
  }

  const formatText = (text: string) => {
    return text
      .replace(/\*\*(.*?)\*\*/g, '<strong class="font-semibold text-gray-900">$1</strong>')
      .replace(
        /^## (.*$)/gm,
        '<h3 class="text-lg font-semibold text-gray-800 mt-6 mb-3 border-b border-gray-400 pb-1 flex items-center gap-2"><span class="text-gray-700">▍</span>$1</h3>',
      )
      .replace(
        /^### (.*$)/gm,
        '<h4 class="text-base font-semibold text-gray-700 mt-4 mb-2">$1</h4>',
      )
      .replace(
        /^- (.*$)/gm,
        '<li class="ml-4 mb-1 text-gray-800 flex items-start gap-2"><span class="text-gray-600 mt-1 text-xs">●</span><span>$1</span></li>',
      )
      .replace(
        /\*\*\$\$([0-9.]+)\*\* USD\/month/g,
        '<span class="inline-flex items-center px-3 py-1 rounded-full bg-green-100 border border-green-400 text-green-800 font-semibold text-sm">$$$1 USD/month</span>',
      )
      .replace(
        /([a-f0-9]{8})/g,
        '<span class="px-2 py-1 rounded bg-purple-100 text-purple-800 text-sm font-mono border border-purple-400 font-semibold">$1</span>',
      )
      .replace(
        /\*\*Environment:\*\* (\w+)/g,
        '<span class="inline-flex items-center gap-1"><strong class="text-gray-900">Environment:</strong> <span class="px-2 py-0.5 rounded bg-blue-100 text-blue-800 text-sm font-medium border border-blue-400">$1</span></span>',
      )
      .replace(
        /\*\*Location:\*\* (\w+)/g,
        '<span class="inline-flex items-center gap-1"><strong class="text-gray-900">Location:</strong> <span class="px-2 py-0.5 rounded bg-cyan-100 text-cyan-800 text-sm font-medium border border-cyan-400">$1</span></span>',
      )
      .replace(
        /`([^`]+)`/g,
        '<code class="px-1.5 py-0.5 rounded bg-gray-200 text-gray-800 text-sm font-mono border border-gray-400">$1</code>',
      )
  }

  const parts = parseContent(content)

  return (
    <div className="space-y-2">
      {parts.map((part, index) => {
        if (part.type === 'code') {
          return (
            <CodeBlock
              key={index}
              language={part.language as string}
              code={part.content}
              onCopy={onCopy}
            />
          )
        }
        return (
          <div
            key={index}
            className="text-sm leading-relaxed text-black"
            dangerouslySetInnerHTML={{
              __html: formatText(part.content).replace(/\n/g, '<br>'),
            }}
          />
        )
      })}
    </div>
  )
}

export default MessageContent
