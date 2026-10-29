import { useState } from 'react'
import type { SourceSpan } from '../types'
import { getMaterialContent } from '../api'

interface Props {
  sessionId: string
  span: SourceSpan
  /** 默认折叠,点击展开查看片段在全文中的上下文 */
  defaultOpen?: boolean
}

/**
 * 原文锚点展示器:证据链最底层的可视化。
 * 展示 snippet,并可展开加载全文、高亮 [start_char, end_char) 区间,
 * 让学生亲眼核对"依据确实在原文里"。
 */
export function SourceSpanView({ sessionId, span, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen)
  const [fullText, setFullText] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function toggle() {
    const next = !open
    setOpen(next)
    if (next && fullText === null) {
      setLoading(true)
      try {
        const doc = await getMaterialContent(sessionId, span.material_id)
        setFullText(doc.content)
      } catch {
        setFullText('(加载原文失败)')
      } finally {
        setLoading(false)
      }
    }
  }

  return (
    <div className="span-view">
      <div className="span-snippet-box">
        <span className="span-quote">“</span>
        <code className="span-snippet">{span.snippet}</code>
        <span className="span-quote">”</span>
        <button className="span-toggle" onClick={toggle}>
          {open ? '收起上下文' : '查看原文上下文'}
        </button>
      </div>
      <div className="span-meta">
        位置:字符 {span.start_char}–{span.end_char} · 材料 {span.material_id}
      </div>
      {open && (
        <div className="span-context">
          {loading && <div className="muted">加载原文中…</div>}
          {fullText !== null && !loading && (
            <pre className="span-fulltext">
              {fullText.slice(Math.max(0, span.start_char - 200), span.end_char + 200)
                .split('')
                .map((ch, i) => {
                  const abs = Math.max(0, span.start_char - 200) + i
                  const inSpan = abs >= span.start_char && abs < span.end_char
                  return inSpan ? (
                    <mark key={i}>{ch}</mark>
                  ) : (
                    <span key={i}>{ch}</span>
                  )
                })}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}