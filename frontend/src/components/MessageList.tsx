import { useEffect, useRef, type ReactNode } from 'react'
import type { AnthropicMessage, ToolResultBlock } from '../types'
import { MessageBubble } from './MessageBubble'
import { ToolCallCard } from './ToolCallCard'

interface Props {
  messages: AnthropicMessage[]
  loading: boolean
  exampleQuestions: string[]
  onPickExample: (question: string) => void
}

export function MessageList({
  messages,
  loading,
  exampleQuestions,
  onPickExample,
}: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to the newest content whenever messages change or a request starts.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  // Index every tool_result by its tool_use_id so each tool_use can be rendered
  // together with its result in a single ToolCallCard.
  const resultsById = new Map<string, ToolResultBlock>()
  for (const message of messages) {
    if (Array.isArray(message.content)) {
      for (const block of message.content) {
        if (block.type === 'tool_result') {
          resultsById.set(block.tool_use_id, block)
        }
      }
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6">
        {messages.length === 0 && (
          <EmptyState questions={exampleQuestions} onPick={onPickExample} />
        )}

        {messages.map((message, mi) => renderMessage(message, mi, resultsById))}

        {loading && <TypingIndicator />}

        <div ref={bottomRef} />
      </div>
    </div>
  )
}

function renderMessage(
  message: AnthropicMessage,
  mi: number,
  resultsById: Map<string, ToolResultBlock>,
): ReactNode {
  if (typeof message.content === 'string') {
    return (
      <MessageBubble key={mi} role={message.role} text={message.content} />
    )
  }

  const nodes: ReactNode[] = []
  message.content.forEach((block, bi) => {
    const key = `${mi}-${bi}`
    if (block.type === 'text') {
      if (block.text.trim()) {
        nodes.push(<MessageBubble key={key} role={message.role} text={block.text} />)
      }
    } else if (block.type === 'tool_use') {
      nodes.push(
        <ToolCallCard
          key={key}
          toolUse={block}
          toolResult={resultsById.get(block.id)}
        />,
      )
    }
    // 'thinking' blocks are intentionally not rendered.
    // 'tool_result' blocks are rendered above, paired with their tool_use.
  })
  return nodes
}

function EmptyState({
  questions,
  onPick,
}: {
  questions: string[]
  onPick: (q: string) => void
}) {
  return (
    <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-900">
        Ask a question about the CDISCPILOT01 dataset
      </h2>
      <p className="mt-1.5 text-sm text-slate-600">
        Every answer is backed by a real SQL query or data-quality check run against
        the database — nothing is answered from memory. Try one of these:
      </p>
      <div className="mt-4 flex flex-col gap-2">
        {questions.map((q) => (
          <button
            key={q}
            onClick={() => onPick(q)}
            className="rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-left text-sm text-slate-700 transition hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-900"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-1 rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <Dot delay="0ms" />
        <Dot delay="150ms" />
        <Dot delay="300ms" />
      </div>
    </div>
  )
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400"
      style={{ animationDelay: delay }}
    />
  )
}
