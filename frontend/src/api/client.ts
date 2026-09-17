import type { ChatMessage, DocDetail, HealthInfo, SourceItem, ToolItem } from '../types'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

function authHeaders(): HeadersInit {
  const key = import.meta.env.VITE_API_KEY as string | undefined
  return key ? { 'X-API-Key': key } : {}
}

export async function fetchHealth(): Promise<HealthInfo> {
  // 经 Vite 代理访问，避免跨域；失败即判定后端未连上
  const res = await fetch(`${API_BASE}/api/v1/health`, {
    headers: { ...authHeaders() },
  })
  if (!res.ok) throw new Error(`health ${res.status}`)
  return res.json()
}

export async function fetchDocDetail(docId: string): Promise<DocDetail> {
  const res = await fetch(
    `${API_BASE}/api/v1/kb/doc?doc_id=${encodeURIComponent(docId)}`,
    { headers: { ...authHeaders() } },
  )
  if (!res.ok) throw new Error(`doc ${res.status}`)
  return res.json()
}

export interface StreamCallbacks {
  onIntent?: (data: {
    intent: string
    intent_name?: string
    confidence?: number
  }) => void
  onToolStart?: (data: { tool: string }) => void
  onToolResult?: (data: ToolItem) => void
  onSources?: (data: { sources: SourceItem[] }) => void
  onReasoning?: (delta: string) => void
  onToken?: (token: string) => void
  onDone?: (data: {
    answer?: string
    intent?: string
    sources?: SourceItem[]
    tools?: ToolItem[]
    handoff?: boolean
    risk_flags?: string[]
    latency_ms?: number
    after_sales_state?: string
    session_id?: string
  }) => void
  onError?: (message: string) => void
}

/** POST SSE：按 event 行解析后转发回调 */
export async function streamChat(
  payload: { user_id: string; session_id?: string | null; message: string },
  cb: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      // sse-starlette 返回 text/event-stream；不使用 EventSource（不支持 POST）
      Accept: 'text/event-stream',
      ...authHeaders(),
    },
    body: JSON.stringify({
      user_id: payload.user_id,
      session_id: payload.session_id,
      message: payload.message,
    }),
    signal,
    cache: 'no-store',
  })

  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `stream HTTP ${res.status}`)
  }
  if (!res.body) {
    throw new Error('stream body empty')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const handleEvent = (raw: string) => {
    // sse-starlette 默认用 \r\n 作行分隔符，需同时兼容 \n
    const lines = raw.split(/\r?\n/)
    let event = 'message'
    let data = ''
    for (const line of lines) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data += line.slice(5).trim()
    }
    if (!data) return
    let parsed: unknown
    try {
      parsed = JSON.parse(data)
    } catch {
      return
    }
    const obj = parsed as Record<string, unknown>
    switch (event) {
      case 'intent':
        cb.onIntent?.(obj as never)
        break
      case 'tool_start':
        cb.onToolStart?.(obj as never)
        break
      case 'tool_result':
        cb.onToolResult?.(obj as unknown as ToolItem)
        break
      case 'sources':
        cb.onSources?.(obj as unknown as { sources: SourceItem[] })
        break
      case 'reasoning':
        cb.onReasoning?.(String(obj.text ?? ''))
        break
      case 'token':
        cb.onToken?.(String(obj.token ?? ''))
        break
      case 'done':
        cb.onDone?.(obj as never)
        break
      case 'error':
        cb.onError?.(String(obj.message ?? 'stream error'))
        break
      default:
        break
    }
  }

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // 兼容 sse-starlette 的 \r\n\r\n 帧分隔（\n\n 无法切分 \r\n\r\n）
    const parts = buffer.split(/\r?\n\r?\n/)
    buffer = parts.pop() ?? ''
    for (const part of parts) {
      if (part.trim()) handleEvent(part)
    }
  }
  if (buffer.trim()) handleEvent(buffer)
}

export function samplePrompts(): string[] {
  return [
    '我的订单到哪了',
    '怎么申请退换货',
    '有什么优惠活动',
    '转人工客服',
  ]
}

export type { ChatMessage }
