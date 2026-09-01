import type { AnthropicMessage, ChatResponse } from './types'

const BASE_URL = import.meta.env.VITE_API_URL

/**
 * Send the full conversation to the backend and get back only the messages
 * generated this turn (assistant tool_use, tool_result, final assistant text).
 * The caller appends these to its own history.
 */
export async function postChat(
  messages: AnthropicMessage[],
): Promise<AnthropicMessage[]> {
  let res: Response
  try {
    res = await fetch(`${BASE_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages }),
    })
  } catch {
    throw new Error(
      `Could not reach the backend at ${BASE_URL}. Is uvicorn running?`,
    )
  }

  if (!res.ok) {
    let detail = `Request failed (HTTP ${res.status})`
    try {
      const body = (await res.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      // response body wasn't JSON — keep the generic message
    }
    throw new Error(detail)
  }

  const data = (await res.json()) as ChatResponse
  return data.new_messages
}
