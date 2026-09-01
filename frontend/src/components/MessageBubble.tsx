import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Role } from '../types'

interface Props {
  role: Role
  text: string
}

export function MessageBubble({ role, text }: Props) {
  if (role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2.5 text-sm text-white">
          {text}
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start">
      <div className="md max-w-[92%] rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-4 py-3 text-sm text-slate-800 shadow-sm">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </div>
    </div>
  )
}
