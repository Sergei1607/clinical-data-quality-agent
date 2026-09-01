import { useCallback, useState } from 'react'
import { postChat } from '../api'
import type { AnthropicMessage } from '../types'
import { ChatInput } from './ChatInput'
import { MessageList } from './MessageList'

// Real questions lifted from backend/scripts/test_chat.py — one per tool.
const EXAMPLE_QUESTIONS = [
  'Give me a high-level overview of this dataset — how many subjects, how are they split across treatment arms, and how do the adverse events break down by severity?',
  'Which subjects had a SEVERE adverse event with a fatal outcome? Give me their usubjid, age, sex, and treatment arm, plus the adverse-event term.',
  'Run the data-quality scan on this dataset and tell me what you find, in plain language, with any clinical significance called out.',
]

export function ChatWindow() {
  const [messages, setMessages] = useState<AnthropicMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const send = useCallback(
    async (text: string): Promise<boolean> => {
      const trimmed = text.trim()
      if (!trimmed || loading) return false

      setError(null)
      const history = [...messages, { role: 'user', content: trimmed } as AnthropicMessage]
      setMessages(history)
      setLoading(true)

      try {
        const newMessages = await postChat(history)
        setMessages([...history, ...newMessages])
        return true
      } catch (e) {
        setMessages(messages) // roll back the optimistic user message
        setError(e instanceof Error ? e.message : 'Something went wrong.')
        return false
      } finally {
        setLoading(false)
      }
    },
    [messages, loading],
  )

  return (
    <div className="flex h-screen flex-col bg-slate-50">
      <Header />

      <MessageList
        messages={messages}
        loading={loading}
        exampleQuestions={EXAMPLE_QUESTIONS}
        onPickExample={(q) => {
          void send(q)
        }}
      />

      {error && (
        <div className="mx-auto w-full max-w-3xl px-4">
          <p className="mb-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            {error}
          </p>
        </div>
      )}

      <ChatInput onSend={send} disabled={loading} />
    </div>
  )
}

function Header() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto w-full max-w-3xl px-4 py-3">
        <h1 className="text-base font-semibold text-slate-900">
          Clinical Data-Quality Reviewer
        </h1>
        <p className="mt-0.5 text-xs text-slate-500">
          CDISCPILOT01 study · 306 subjects · 1,191 adverse events · DM · AE · VS · LB
          domains · answers backed by live SQL
        </p>
      </div>
    </header>
  )
}
