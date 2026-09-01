// Anthropic message format — the frontend owns the full conversation history and
// sends it to POST /chat on every turn. These types mirror what the backend
// (backend/app/agent.py) produces and accepts.

export type Role = 'user' | 'assistant'

export interface TextBlock {
  type: 'text'
  text: string
}

export interface ThinkingBlock {
  type: 'thinking'
  thinking: string
  signature?: string
}

export interface ToolUseBlock {
  type: 'tool_use'
  id: string
  name: string
  input: Record<string, unknown>
}

export interface ToolResultBlock {
  type: 'tool_result'
  tool_use_id: string
  content: string
  is_error?: boolean
}

export type ContentBlock = TextBlock | ThinkingBlock | ToolUseBlock | ToolResultBlock

export interface AnthropicMessage {
  role: Role
  // The first user message we create is a plain string; everything the backend
  // returns is an array of content blocks.
  content: string | ContentBlock[]
}

export interface ChatResponse {
  new_messages: AnthropicMessage[]
}
