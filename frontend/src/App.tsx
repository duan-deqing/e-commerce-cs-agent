import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Headset, WarningCircle } from '@phosphor-icons/react'
import { fetchHealth, streamChat } from './api/client'
import { Composer } from './components/Composer'
import { Ledger } from './components/Ledger'
import type { ChatMessage, HealthInfo, TraceEvent } from './types'

const USER_ID = 'u_1001'

function uid(prefix = 'm'): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
}

function previewData(data: unknown): string {
  if (data == null) return ''
  const d = data as Record<string, unknown>
  if (d.found === false) return String(d.message ?? '未找到')
  if (d.order) {
    const o = d.order as { order_id?: string; status?: string; amount?: number }
    return `${o.order_id ?? ''} · ${o.status ?? ''} · ¥${o.amount ?? ''}`
  }
  if (d.orders && Array.isArray(d.orders)) return `共 ${d.orders.length} 笔订单`
  if (d.tracking) {
    const t = d.tracking as { tracking_no?: string; status?: string; carrier?: string }
    return `${t.carrier ?? ''} ${t.tracking_no ?? ''} · ${t.status ?? ''}`
  }
  if (d.ticket) {
    const t = d.ticket as { ticket_id?: string; status?: string; type?: string }
    return `${t.ticket_id ?? ''} · ${t.type ?? ''} · ${t.status ?? ''}`
  }
  if (d.campaigns && Array.isArray(d.campaigns)) {
    const names = d.campaigns.slice(0, 2).map((c) => (c as { name?: string }).name)
    return names.join('、') || '活动'
  }
  if (d.success === true) return '成功'
  try {
    return JSON.stringify(d).slice(0, 80)
  } catch {
    return '完成'
  }
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [health, setHealth] = useState<HealthInfo | null>(null)
  const [connection, setConnection] = useState<'checking' | 'ok' | 'fail'>('checking')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sessionIdRef = useRef<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    let cancelled = false
    setConnection('checking')
    fetchHealth()
      .then((h) => {
        if (cancelled) return
        setHealth(h)
        setConnection(h.status === 'ok' ? 'ok' : 'fail')
      })
      .catch(() => {
        if (cancelled) return
        setHealth({
          status: 'unreachable',
          env: 'unknown',
          mock_llm: true,
          chroma_ready: false,
          tools_registered: 0,
        })
        setConnection('fail')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const resetSession = useCallback(() => {
    abortRef.current?.abort()
    sessionIdRef.current = null
    setMessages([])
    setError(null)
    setBusy(false)
  }, [])

  const send = useCallback(async (text: string) => {
    setError(null)
    const userMsgId = uid()
    const assistantId = uid()
    setMessages((prev) => [
      ...prev,
      { id: userMsgId, role: 'user', content: text, createdAt: Date.now() },
      { id: assistantId, role: 'assistant', content: '', createdAt: Date.now(), streaming: true, trace: [] },
    ])
    setBusy(true)

    const controller = new AbortController()
    abortRef.current = controller

    let acc = ''
    let currentTrace: TraceEvent[] = []

    const pushTrace = (event: Omit<TraceEvent, 'id' | 'ts'>) => {
      const item: TraceEvent = { ...event, id: uid('t'), ts: Date.now() }
      currentTrace = [...currentTrace, item]
      setMessages((prev) =>
        prev.map((m) => (m.id === assistantId ? { ...m, trace: currentTrace } : m)),
      )
      return item
    }

    const patchAssistant = (patch: Partial<ChatMessage>) => {
      setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, ...patch } : m)))
    }

    pushTrace({
      kind: 'token',
      title: '会话开始',
      detail: `发送用户消息：${text.slice(0, 40)}${text.length > 40 ? '…' : ''}`,
      status: 'run',
      meta: `user_id=${USER_ID}`,
    })

    try {
      await streamChat(
        { user_id: USER_ID, session_id: sessionIdRef.current, message: text },
        {
          onIntent: (d) => {
            pushTrace({
              kind: 'intent',
              title: '意图识别',
              detail: `${d.intent_name || d.intent} · ${d.intent}`,
              status: 'ok',
              meta: `confidence=${((d.confidence ?? 0) * 100).toFixed(0)}%`,
            })
            patchAssistant({ intent: d.intent, intentName: d.intent_name, confidence: d.confidence })
          },
          onToolStart: (d) => {
            pushTrace({
              kind: 'tool_start',
              title: `调用工具 ${d.tool}`,
              detail: '参数校验通过，开始执行…',
              status: 'run',
              meta: d.tool,
            })
          },
          onToolResult: (d) => {
            pushTrace({
              kind: 'tool_result',
              title: d.success ? `工具成功 · ${d.tool}` : `工具失败 · ${d.tool}`,
              detail: d.success ? previewData(d.data) : String(d.error || '未知错误'),
              status: d.success ? 'ok' : 'fail',
              meta:
                d.latency_ms != null
                  ? `latency=${d.latency_ms}ms${d.retried ? ` retry=${d.retried}` : ''}`
                  : d.tool,
            })
          },
          onSources: (d) => {
            const list = d.sources ?? []
            pushTrace({
              kind: 'sources',
              title: 'RAG 知识检索',
              detail:
                list.length > 0
                  ? list.map((s) => s.title || s.doc_id).slice(0, 3).join('；')
                  : '无高置信命中',
              status: list.length ? 'ok' : 'fail',
              meta: `sources=${list.length}`,
            })
            patchAssistant({ sources: list })
          },
          onToken: (token) => {
            acc += token
            patchAssistant({ content: acc, streaming: true })
          },
          onDone: (d) => {
            if (d.session_id) sessionIdRef.current = d.session_id
            const answer = d.answer || acc
            pushTrace({
              kind: 'done',
              title: '生成完成',
              detail: answer.slice(0, 80) + (answer.length > 80 ? '…' : ''),
              status: 'ok',
              meta:
                d.latency_ms != null
                  ? `total=${d.latency_ms}ms${d.after_sales_state ? ` · ${d.after_sales_state}` : ''}`
                  : undefined,
            })
            patchAssistant({
              content: answer,
              streaming: false,
              sources: d.sources ?? undefined,
              tools: d.tools ?? undefined,
              handoff: d.handoff,
              riskFlags: d.risk_flags,
              trace: currentTrace,
            })
            setConnection('ok')
          },
          onError: (msg) => {
            pushTrace({
              kind: 'error',
              title: '执行异常',
              detail: msg,
              status: 'fail',
            })
            setError(msg)
            patchAssistant({ content: acc || '请求失败，请重试。', streaming: false, error: msg })
          },
        },
        controller.signal,
      )
      patchAssistant({ streaming: false, trace: currentTrace })
    } catch (e) {
      // 用户点"新会话"主动中断，不当作错误上报
      if (controller.signal.aborted) return
      const msg = e instanceof Error ? e.message : String(e)
      pushTrace({
        kind: 'error',
        title: '连接失败',
        detail: msg,
        status: 'fail',
        meta: '检查后端是否已启动，以及 Vite 代理 /api → :8000',
      })
      setError(`连接失败：${msg}`)
      patchAssistant({ content: acc || `连接失败：${msg}`, streaming: false, error: `连接失败：${msg}` })
      setConnection('fail')
    } finally {
      setBusy(false)
    }
  }, [])

  const statusLabel = useMemo(() => {
    if (busy) return '客服正在处理…'
    if (connection === 'ok') return '在线'
    if (connection === 'fail') return '连接失败'
    return '连接中'
  }, [busy, connection])

  return (
    <div className="app-shell">
      <section className="dialog" aria-label="客服对话窗口">
        <header className="top-strip">
          <div className="brand">
            <div className="brand-mark" aria-hidden>
              <Headset size={19} weight="duotone" />
            </div>
            <div>
              <div className="brand-name">
                Orbit <em>Desk</em>
              </div>
              <div className="brand-sub">电商智能客服</div>
            </div>
          </div>
          <div className="top-meta">
            <span className="meta-pill">
              <i className={`dot ${connection === 'ok' ? 'ok' : connection === 'fail' ? 'bad' : ''}`} />
              {statusLabel}
            </span>
            <span className="meta-pill soft">{health?.mock_llm ? '演示模式' : '智能模型'}</span>
          </div>
        </header>

        <div className="chat-pane">
          <Ledger messages={messages} onPrompt={send} />
          {error && !busy ? (
            <div className="error-banner" role="alert">
              <WarningCircle size={15} weight="fill" />
              {error}
            </div>
          ) : null}
          <Composer busy={busy} onSend={send} onReset={resetSession} />
        </div>
      </section>
    </div>
  )
}
