export type Role = 'system' | 'user' | 'assistant' | 'tool'

export interface ToolCall {
  id: string
  type: 'function'
  function: { name: string; arguments: string }
}

export interface ChatMessage {
  role: Role
  content: string | null
  tool_calls?: ToolCall[]
  tool_call_id?: string
}

export interface SessionSummary {
  id: string
  title: string
  model: string
  updated_at: number
  message_count: number
  usage?: Usage
}

export interface Usage {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
  cost?: number
}

export interface SessionFull {
  id: string
  title: string
  model: string
  created_at: number
  updated_at: number
  messages: ChatMessage[]
  usage?: Usage
}

export interface ModelInfo {
  id: string
  name: string
  context: number | null
  prompt_price: number
  completion_price: number
}

export interface UsageTotals {
  sessions: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost: number
}

export interface Settings {
  ok: boolean
  demo: boolean
  model: string
  key_masked: string | null
  default_models: string[]
  approval_mode: 'guarded' | 'ask' | 'auto'
  docker_sandbox: boolean
  docker_available: boolean
}

export interface McpServerStatus {
  name: string
  command: string
  args: string[]
  enabled: boolean
  status: 'stopped' | 'starting' | 'ready' | 'error'
  error: string | null
  tools: string[]
}

export interface FileNode {
  name: string
  type: 'dir' | 'file'
  path?: string
  size?: number
  children?: FileNode[]
}

export type AgentEvent =
  | { type: 'reasoning_delta'; text: string }
  | { type: 'assistant_delta'; text: string }
  | { type: 'assistant_message'; content: string | null; tool_calls: ToolCall[] | null }
  | { type: 'tool_start'; id: string; name: string; args: Record<string, unknown> }
  | { type: 'tool_result'; id: string; name: string; args: Record<string, unknown>; ok: boolean; output: string }
  | { type: 'approval_request'; id: string; command: string; level: string; reasons: string[] }
  | { type: 'approval_decision'; id: string; decision: string }
  | { type: 'turn_end'; usage: unknown; session_usage?: Usage; message_count: number }
  | { type: 'mcp_ready'; tools: string[] }
  | { type: 'error'; message: string }
  | { type: 'done' }

export type TaskDoneEvent = { type: 'task_done'; index: number; session_id: string }

export type BatchEvent =
  | { type: 'task_created'; index: number; session_id: string; title: string }
  | { type: 'task_event'; index: number; event: AgentEvent | TaskDoneEvent }
  | { type: 'batch_done'; tasks: { index: number; session_id: string; title: string }[] }
  | { type: 'error'; message: string }
  | { type: 'done' }

export interface TaskGroup {
  index: number
  sessionId: string
  title: string
  status: 'running' | 'done' | 'error'
  items: Item[]
}

export type Item =
  | { kind: 'user'; id: string; text: string }
  | { kind: 'assistant'; id: string; text: string; streaming: boolean }
  | { kind: 'reasoning'; id: string; text: string; streaming: boolean }
  | {
      kind: 'tool'
      id: string
      callId: string
      name: string
      args: Record<string, unknown>
      output: string | null
      ok: boolean | null
    }
  | {
      kind: 'approval'
      id: string
      approvalId: string
      command: string
      level: string
      reasons: string[]
      decision: string | null
    }
  | { kind: 'error'; id: string; message: string }

let counter = 0
export function uid(): string {
  counter += 1
  return `i${Date.now().toString(36)}${counter}`
}
