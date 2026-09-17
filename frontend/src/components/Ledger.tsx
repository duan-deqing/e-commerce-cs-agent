import { useEffect, useRef } from 'react'
import { Headset, WarningCircle } from '@phosphor-icons/react'
import type { ChatMessage } from '../types'
import { samplePrompts } from '../api/client'
import { TracePanel } from './TracePanel'
import { SourceCard } from './SourceCard'

interface Props {
  messages: ChatMessage[]
  onPrompt: (text: string) => void
}

export function Ledger({ messages, onPrompt }: Props) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  return (
    <div className="thread" id="ledger">
      {messages.length === 0 ? (
        <Welcome onPrompt={onPrompt} />
      ) : null}

      <div className="thread-inner">
        {messages.map((m) => (
          <article
            key={m.id}
            className={`msg ${m.role}${m.streaming ? ' streaming' : ''}`}
          >
            {m.role === 'assistant' && m.trace?.length ? (
              <TracePanel trace={m.trace} streaming={Boolean(m.streaming)} />
            ) : null}
            <div className="bubble">{m.content}</div>

            {m.error ? (
              <div className="msg-error">
                <WarningCircle size={14} weight="fill" />
                {m.error}
              </div>
            ) : null}

            {m.role === 'assistant' ? (
              <div className="attach">
                {m.handoff ? (
                  <div className="flag-row">
                    <span className="flag info">已转接人工客服</span>
                  </div>
                ) : null}
                {m.riskFlags?.length ? (
                  <div className="flag-row">
                    {m.riskFlags.map((f) => (
                      <span key={f} className="flag warn">
                        <WarningCircle size={12} weight="fill" />
                        {f}
                      </span>
                    ))}
                  </div>
                ) : null}
                {m.sources?.length ? (
                  <div className="src-list">
                    {m.sources.slice(0, 3).map((s) => (
                      <SourceCard key={s.doc_id} source={s} />
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </article>
        ))}
      </div>
      <div ref={endRef} />
    </div>
  )
}

function Welcome({ onPrompt }: { onPrompt: (text: string) => void }) {
  return (
    <div className="welcome">
      <span className="welcome-badge">
        <Headset size={15} weight="fill" style={{ color: 'var(--accent)' }} />
        在线客服 · 平均响应 1 秒
      </span>
      <h1>
        你好，我是<em>购物助手</em>
        <br />
        订单、物流、售后，问我就好
      </h1>
      <p>可以直接描述问题，比如查询订单进度、了解优惠活动，或发起退换货申请。我会自动调用查询工具，为你找到准确答案。</p>
      <div className="suggest">
        {samplePrompts().map((p) => (
          <button key={p} type="button" className="chip" onClick={() => onPrompt(p)}>
            {p}
          </button>
        ))}
      </div>
    </div>
  )
}
