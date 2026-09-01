import { useRef, useState, type KeyboardEvent } from 'react'

interface Props {
  onSend: (text: string) => Promise<boolean>
  disabled: boolean
}

export function ChatInput({ onSend, disabled }: Props) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const submit = async () => {
    const text = value
    if (!text.trim() || disabled) return
    setValue('')
    resetHeight()
    const ok = await onSend(text)
    if (!ok) setValue(text) // restore on failure so nothing is lost
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void submit()
    }
  }

  const resetHeight = () => {
    const el = textareaRef.current
    if (el) el.style.height = 'auto'
  }

  const grow = () => {
    const el = textareaRef.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = `${Math.min(el.scrollHeight, 160)}px`
    }
  }

  return (
    <div className="border-t border-slate-200 bg-white">
      <div className="mx-auto flex w-full max-w-3xl items-end gap-2 px-4 py-3">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => {
            setValue(e.target.value)
            grow()
          }}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder="Ask about the CDISCPILOT01 dataset…"
          disabled={disabled}
          className="max-h-40 flex-1 resize-none rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-800 outline-none placeholder:text-slate-400 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-50 disabled:text-slate-400"
        />
        <button
          onClick={() => void submit()}
          disabled={disabled || !value.trim()}
          className="shrink-0 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {disabled ? 'Thinking…' : 'Send'}
        </button>
      </div>
    </div>
  )
}
