import { useEffect, useRef, useState } from 'react'
import {
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

      <div className={`trace-body${open ? ' open' : ''}`}>
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
                    {e.detail ? <div className="step-detail">{e.detail}</div> : null}
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
