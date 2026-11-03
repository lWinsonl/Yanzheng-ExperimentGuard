import { useEffect, useRef, useState } from 'react'
import type { ReviewSession } from '../types'
import { getSession, listSessions } from '../api'

interface Props {
  currentSessionId?: string
  onOpen: (session: ReviewSession) => void
  onClose: () => void
}

const EXPERIMENT_LABELS: Record<string, string> = {
  data_model: '数据与模型实验',
  algorithm_system: '算法与系统性能实验',
}

export function SessionHistory({ currentSessionId, onOpen, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const active = useRef(true)
  const [sessions, setSessions] = useState<ReviewSession[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [opening, setOpening] = useState<string | null>(null)
  const [refreshVersion, setRefreshVersion] = useState(0)

  useEffect(() => {
    active.current = true
    dialog.current?.showModal()
    return () => { active.current = false }
  }, [])

  useEffect(() => {
    let valid = true
    listSessions().then(value => {
      if (!valid) return
      setSessions([...value].sort((a, b) => b.created_at.localeCompare(a.created_at)))
      setLoading(false)
    }).catch(() => {
      if (!valid) return
      setError('暂时无法读取历史会话，请重试。')
      setLoading(false)
    })
    return () => { valid = false }
  }, [refreshVersion])

  function refresh() {
    setLoading(true)
    setError('')
    setRefreshVersion(version => version + 1)
  }

  async function openSession(id: string) {
    setOpening(id)
    setError('')
    try {
      const session = await getSession(id)
      if (active.current) onOpen(session)
    } catch {
      if (active.current) setError('该会话暂时无法打开，可能已被清理或连接中断。当前审查仍然保留，请刷新列表后再试。')
    } finally {
      if (active.current) setOpening(null)
    }
  }

  return <dialog ref={dialog} className="history-dialog" aria-labelledby="history-title" onClose={onClose}>
    <div className="agent-section-header">
      <h2 id="history-title">历史审查会话</h2>
      <button onClick={() => dialog.current?.close()} autoFocus>关闭</button>
    </div>
    <p className="muted">显示当前浏览器可访问的记录，按创建时间从新到旧排列。</p>
    {loading && <p role="status">正在读取历史会话…</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {!loading && !error && sessions.length === 0 && <p className="muted">
      当前浏览器没有可用的历史会话。请确认使用相同的浏览器和网址；演示环境更新或重启后，记录也可能已被清空。
    </p>}
    {!loading && sessions.length > 0 && <div className="session-history-list">
      {sessions.map(session => <button key={session.session_id} className="session-history-item"
        disabled={opening !== null} onClick={() => openSession(session.session_id)}>
        <span className="session-history-title">{session.title.trim() || '未命名审查'}</span>
        <span className="session-history-meta">
          {EXPERIMENT_LABELS[session.experiment_type] ?? session.experiment_type}
          {' · '}{session.claims.length} 条主张{' · '}
          {new Date(session.created_at).toLocaleDateString('zh-CN')}
        </span>
        {session.session_id === currentSessionId && <span className="muted">当前会话</span>}
        {opening === session.session_id && <span>正在打开…</span>}
      </button>)}
    </div>}
    <div className="page-actions">
      <button disabled={loading || opening !== null} onClick={refresh}>刷新列表</button>
    </div>
  </dialog>
}
