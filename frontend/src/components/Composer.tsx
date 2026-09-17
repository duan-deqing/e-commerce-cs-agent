import { useEffect, useRef, useState } from 'react'
import { ArrowUp, ArrowsCounterClockwise } from '@phosphor-icons/react'

interface Props {
  busy: boolean
  onSend: (text: string) => void
  onReset: () => void
}

export function Composer({ busy, onSend, onReset }: Props) {
  const [value, setValue] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    ref.current?.focus()
  }, [])

  const submit = () => {
    const text = value.trim()
    if (!text || busy) return
    onSend(text)
    setValue('')
    // 重置自适应高度，避免发送长文本后空输入框保持展开高度
    if (ref.current) ref.current.style.height = 'auto'
  }

  return (
    <div className="composer-wrap">
      <div className="composer">
        <button
          type="button"
          className="icon-btn"
          title="开启新会话"
          aria-label="开启新会话"
          disabled={busy}
          onClick={onReset}
        >
          <ArrowsCounterClockwise size={17} weight="bold" />
        </button>
        <textarea
          ref={ref}
          value={value}
          rows={1}
          placeholder="输入你的问题，Enter 发送"
          onChange={(e) => {
            setValue(e.target.value)
            e.target.style.height = 'auto'
            e.target.style.height = `${Math.min(e.target.scrollHeight, 148)}px`
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
        />
        <button
          type="button"
          className={`send-btn${busy ? ' busy' : ''}`}
          aria-label="发送"
          disabled={busy || !value.trim()}
          onClick={submit}
        >
          <ArrowUp size={18} weight="bold" />
        </button>
      </div>
      <div className="composer-hint">内容由 AI 生成，仅供参考 · 涉及退款等敏感操作将转接人工</div>
    </div>
  )
}
