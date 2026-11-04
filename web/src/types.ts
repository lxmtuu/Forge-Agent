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
}

export interface SessionFull {
  id: string
  title: string
  model: string
  created_at: number
  updated_at: number
  messages: ChatMessage[]
}

export interface Settings {
  ok: boolean
  demo: boolean
  model: string
  key_masked: string | null
  default_models: string[]
  approval_mode: 'guarded' | 'auto'
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
  | { type: 'turn_end'; usage: unknown; message_count: number }
  | { type: 'error'; message: string }
  | { type: 'done' }

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
  | { kind: 'error'; id: string; message: string }

let counter = 0
export function uid(): string {
  counter += 1
  return `i${Date.now().toString(36)}${counter}`
}
