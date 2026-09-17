import { useState } from 'react'
import { CaretDown, FileText, LinkSimple, WarningCircle } from '@phosphor-icons/react'
import { fetchDocDetail } from '../api/client'
import type { DocDetail, SourceItem } from '../types'

/**
 * 引用溯源卡片：点击展开后懒加载知识库文档全文与来源信息。
 */
export function SourceCard({ source }: { source: SourceItem }) {
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<DocDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const toggle = () => {
    const next = !open
    setOpen(next)
    if (next && !detail && !loading && !error) {
      setLoading(true)
      fetchDocDetail(source.doc_id)
        .then(setDetail)
        .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
        .finally(() => setLoading(false))
    }
  }

  const fileName = detail?.source ? detail.source.split(/[\\/]/).pop() : ''

  return (
    <div className={`src-item${open ? ' open' : ''}`}>
      <button type="button" className="src-head" aria-expanded={open} onClick={toggle}>
        <LinkSimple size={13} weight="bold" className="src-ico" aria-hidden />
        <span className="src-title">{source.title || source.doc_id}</span>
        {source.score != null ? (
          <span className="src-score">{Math.round(source.score * 100)}%</span>
        ) : null}
        <CaretDown size={13} className="src-chevron" aria-hidden />
      </button>
      {source.snippet ? <div className="src-snippet">{source.snippet}</div> : null}
      <div className={`src-body${open ? ' open' : ''}`}>
        <div className="src-body-inner">
          {loading ? <div className="src-note">正在加载文档内容…</div> : null}
          {!loading && error ? (
            <div className="src-note err">
              <WarningCircle size={13} weight="fill" />
              文档加载失败（{error}）
            </div>
          ) : null}
          {!loading && detail ? (
            <>
              <div className="src-content">{detail.content}</div>
              <div className="src-origin">
                <FileText size={12} weight="fill" aria-hidden />
                来源：{fileName || '知识库文档'}
                {detail.section ? ` · ${detail.section}` : ''}
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  )
}
