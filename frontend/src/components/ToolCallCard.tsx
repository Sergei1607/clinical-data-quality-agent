import { useState } from 'react'
import type { ToolResultBlock, ToolUseBlock } from '../types'

const TOOL_LABELS: Record<string, string> = {
  run_sql_query: 'Query',
  get_summary_stats: 'Summary Stats',
  run_quality_checks: 'Quality Scan',
}

interface Props {
  toolUse: ToolUseBlock
  toolResult?: ToolResultBlock
}

export function ToolCallCard({ toolUse, toolResult }: Props) {
  const [expanded, setExpanded] = useState(false)

  const label = TOOL_LABELS[toolUse.name] ?? toolUse.name
  const isError = toolResult?.is_error === true
  const sql =
    toolUse.name === 'run_sql_query' ? String(toolUse.input.query ?? '') : null

  const parsed = parseContent(toolResult?.content)
  const { preview, full, count } = summarize(parsed)
  const collapsible = full !== preview

  const frame = isError
    ? 'border-amber-300 bg-amber-50'
    : 'border-slate-300 bg-slate-50'
  const headerTone = isError ? 'text-amber-800' : 'text-slate-500'

  return (
    <div className="flex justify-start">
      <div
        className={`w-full max-w-[92%] overflow-hidden rounded-xl border font-mono text-xs ${frame}`}
      >
        <div
          className={`flex items-center gap-2 border-b border-black/5 px-3 py-1.5 ${headerTone}`}
        >
          <span className="rounded bg-black/5 px-1.5 py-0.5 font-semibold tracking-wide uppercase">
            {isError ? 'Tool error' : label}
          </span>
          {!isError && count != null && (
            <span>
              {count} {count === 1 ? 'row' : 'rows'}
            </span>
          )}
        </div>

        {sql && (
          <pre className="overflow-x-auto px-3 py-2 whitespace-pre-wrap text-slate-800">
            {sql}
          </pre>
        )}

        {!toolResult && (
          <p className="px-3 py-2 text-slate-400">running…</p>
        )}

        {toolResult && isError && (
          <p
            className={`px-3 py-2 text-amber-800 ${sql ? 'border-t border-amber-200' : ''}`}
          >
            {typeof parsed === 'object' && parsed !== null && 'error' in parsed
              ? String((parsed as { error: unknown }).error)
              : full}
          </p>
        )}

        {toolResult && !isError && (
          <div className={sql ? 'border-t border-slate-200' : ''}>
            <pre className="overflow-x-auto px-3 py-2 whitespace-pre-wrap text-slate-700">
              {expanded ? full : preview}
            </pre>
            {collapsible && (
              <button
                onClick={() => setExpanded((v) => !v)}
                className="w-full border-t border-slate-200 px-3 py-1.5 text-left text-slate-500 hover:bg-slate-100"
              >
                {expanded ? '▾ show less' : '▸ show full result'}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

type Parsed = unknown

function parseContent(content?: string): Parsed {
  if (content == null) return null
  try {
    return JSON.parse(content)
  } catch {
    return content
  }
}

/**
 * Turn a parsed tool result into a short preview and a full rendering. `preview`
 * and `full` are equal when the result is already small (no need for a toggle).
 */
function summarize(parsed: Parsed): {
  preview: string
  full: string
  count: number | null
} {
  if (parsed == null) return { preview: '', full: '', count: null }
  if (typeof parsed === 'string') {
    return { preview: parsed, full: parsed, count: null }
  }

  // run_sql_query: { rows: [...], truncated: boolean }
  if (
    typeof parsed === 'object' &&
    'rows' in parsed &&
    Array.isArray((parsed as { rows: unknown[] }).rows)
  ) {
    const { rows, truncated } = parsed as { rows: unknown[]; truncated?: boolean }
    const tail = truncated ? '\n\n(capped at 500 rows)' : ''
    const full = JSON.stringify(rows, null, 2) + tail
    const preview =
      rows.length <= 3
        ? full
        : JSON.stringify(rows.slice(0, 3), null, 2) +
          `\n… ${rows.length - 3} more`
    return { preview, full, count: rows.length }
  }

  // run_quality_checks: array of check objects
  if (Array.isArray(parsed)) {
    const full = JSON.stringify(parsed, null, 2)
    const preview =
      parsed.length <= 2
        ? full
        : JSON.stringify(parsed.slice(0, 2), null, 2) +
          `\n… ${parsed.length - 2} more`
    return { preview, full, count: parsed.length }
  }

  // get_summary_stats and anything else: pretty-print, truncate by line count
  const full = JSON.stringify(parsed, null, 2)
  const lines = full.split('\n')
  const preview =
    lines.length <= 14 ? full : lines.slice(0, 14).join('\n') + '\n…'
  return { preview, full, count: null }
}
