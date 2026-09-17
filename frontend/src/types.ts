export type Role = 'user' | 'assistant' | 'system'

export type TraceKind =
  | 'intent'
  | 'tool_start'
  | 'tool_result'
  | 'sources'
  | 'reasoning'
  | 'token'
  | 'done'
  | 'error'

export interface TraceEvent {
  id: string
  kind: TraceKind
  ts: number
  title: string
  detail: string
  status?: 'ok' | 'fail' | 'run' | 'info'
  meta?: string
}

export interface SourceItem {
  doc_id: string
  title: string
  score?: number | null
  snippet: string
}

export interface DocDetail {
  doc_id: string
  title: string
  content: string
  source: string
  section: string
}

export interface ToolItem {
  tool: string
  success: boolean
  data?: unknown
  error?: string | null
  latency_ms?: number
  retried?: number
}

export interface ChatMessage {
  id: string
  role: Role
  content: string
  createdAt: number
  intent?: string
  intentName?: string
  confidence?: number
  sources?: SourceItem[]
  tools?: ToolItem[]
  handoff?: boolean
  riskFlags?: string[]
  streaming?: boolean
  error?: string
  trace?: TraceEvent[]
}

export interface HealthInfo {
  status: string
  env: string
  mock_llm: boolean
  chroma_ready: boolean
  tools_registered: number
  version?: string
}
