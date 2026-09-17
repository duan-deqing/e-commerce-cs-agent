import { useEffect, useRef, useState, type TransitionEvent } from 'react'
import {
  Brain,
  CaretDown,
  CheckCircle,
  CircleNotch,
  Lightning,
  WarningCircle,
  type Icon,
} from '@phosphor-icons/react'
import type { TraceEvent } from '../types'

interface Props {
  trace: TraceEvent[]
  streaming: boolean
}

const STEP_ICON: Record<string, Icon> = {
  intent: Lightning,
  reasoning: Brain,
  done: CheckCircle,
  error: WarningCircle,
}

function stepIcon(ev: TraceEvent): { Icon: Icon; spin: boolean } {
  if (ev.status === 'run' && ev.kind !== 'done') return { Icon: CircleNotch, spin: true }
  const mapped = STEP_ICON[ev.kind]
  return { Icon: mapped ?? Lightning, spin: false }
}

/**
 * Agent 执行过程：内嵌在消息气泡下方，可折叠。
 * 生成中自动展开，结束且用户未手动操作过时自动收起。
 */
export function TracePanel({ trace, streaming }: Props) {
  const [open, setOpen] = useState(streaming)
  const touchedRef = useRef(false)
  const wasStreaming = useRef(streaming)
  const reasoningRef = useRef<HTMLDivElement | null>(null)
  const reasoningPinnedRef = useRef(true)
  const animatingRef = useRef(false)
  const prevOpenRef = useRef(open)

  // 思考流式文本：新增量到达时吸底展示最新内容；用户上滚即暂停吸底，滚回底部恢复
  const reasoningDetail = trace.find((e) => e.kind === 'reasoning')?.detail ?? ''

  const pinReasoning = () => {
    const el = reasoningRef.current
    if (el && reasoningPinnedRef.current) el.scrollTop = el.scrollHeight
  }

  useEffect(() => {
    // 展开/收起切换后进入动画期：期间 scroll 事件多由高度变化/滚动锚定引起，不据此解吸
    if (prevOpenRef.current !== open) {
      prevOpenRef.current = open
      animatingRef.current = true
    }
    pinReasoning()
  }, [reasoningDetail, open])

  // 动画（grid-template-rows）结束后补一次吸底并退出动画期
  const handleBodyTransitionEnd = (e: TransitionEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget || e.propertyName !== 'grid-template-rows') return
    animatingRef.current = false
    pinReasoning()
  }

  const handleReasoningScroll = () => {
    if (animatingRef.current) return
    const el = reasoningRef.current
    if (!el) return
    reasoningPinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
  }

  useEffect(() => {
    if (streaming && !wasStreaming.current && !touchedRef.current) setOpen(true)
    if (!streaming && wasStreaming.current && !touchedRef.current) setOpen(false)
    wasStreaming.current = streaming
  }, [streaming])

  if (trace.length === 0) return null

  const okCount = trace.filter((t) => t.status === 'ok').length
  const summary = streaming
    ? '正在执行…'
    : `${trace.length} 步 · ${okCount} 项完成`

  return (
    <section className="trace" aria-label="Agent 执行过程">
      <button
        type="button"
        className={`trace-toggle${streaming ? ' has-live' : ''}`}
        aria-expanded={open}
        onClick={() => {
          touchedRef.current = true
          setOpen((v) => !v)
        }}
      >
        <span className="tt-icon" aria-hidden>
          <Lightning size={13} weight="bold" />
        </span>
        <span className="tt-title">执行过程</span>
        <span className="tt-sum">{summary}</span>
        {streaming ? (
          <span className="tt-live">
            <span className="pulse-dot" aria-hidden />
            运行中
          </span>
        ) : null}
        <CaretDown size={14} className={`tt-chevron${open ? ' open' : ''}`} aria-hidden />
      </button>

      <div
        className={`trace-body${open ? ' open' : ''}`}
        onTransitionEnd={handleBodyTransitionEnd}
      >
        <div className="trace-inner">
          <ol className="trace-steps">
            {trace.map((e) => {
              const { Icon, spin } = stepIcon(e)
              return (
                <li key={e.id} className={`step ${e.status ?? 'info'}`}>
                  <span className="step-icon" aria-hidden>
                    <Icon size={12} weight="bold" className={spin ? 'spin' : undefined} />
                  </span>
                  <div className="step-main">
                    <div className="step-title">{e.title}</div>
                    {e.detail ? (
                      e.kind === 'reasoning' ? (
                        // 思考流式文本：限高滚动，可查看全部思考内容；tabIndex 让键盘也能滚动
                        <div
                          className="step-detail reasoning"
                          ref={reasoningRef}
                          tabIndex={0}
                          onScroll={handleReasoningScroll}
                        >
                          <span className="reasoning-text">{e.detail}</span>
                        </div>
                      ) : (
                        <div className="step-detail">{e.detail}</div>
                      )
                    ) : null}
                    {e.meta ? <div className="step-meta">{e.meta}</div> : null}
                  </div>
                </li>
              )
            })}
          </ol>
        </div>
      </div>
    </section>
  )
}
