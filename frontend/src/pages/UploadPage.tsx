import { useEffect, useRef, useState } from 'react'
import type { GapAnalysis, IngestResponse, MaterialMeta, MaterialRole } from '../types'
import { addTextMaterial, analyzeGaps, listMaterials, uploadFile } from '../api'
import { DEMO_EXECUTION, DEMO_PLAN } from '../demo-data'

interface Props {
  sessionId: string
  onNext: () => void
  onBack: () => void
}

/** 单个上传区域:计划或执行,各自独立的上传按钮和粘贴框。 */
function UploadArea({
  sessionId,
  role,
  onUploaded,
}: {
  sessionId: string
  role: MaterialRole
  onUploaded: () => void
}) {
  const isPlan = role === 'plan'
  const [pasteMode, setPasteMode] = useState(false)
  const [pasteName, setPasteName] = useState(isPlan ? 'plan.md' : 'train.py')
  const [pasteContent, setPasteContent] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [lastResult, setLastResult] = useState<IngestResponse | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  async function handleUpload(file: File) {
    setBusy(true)
    setError('')
    try {
      const res = await uploadFile(sessionId, role, file)
      setLastResult(res)
      onUploaded()
    } catch (e) {
      setError(e instanceof Error ? e.message : '上传失败')
    } finally {
      setBusy(false)
    }
  }

  async function handlePaste() {
    if (!pasteContent.trim()) return
    setBusy(true)
    setError('')
    try {
      const res = await addTextMaterial(sessionId, role, pasteName, pasteContent)
      setLastResult(res)
      setPasteContent('')
      onUploaded()
    } catch (e) {
      setError(e instanceof Error ? e.message : '提交失败')
    } finally {
      setBusy(false)
    }
  }

  function loadDemo() {
    setPasteMode(true)
    setPasteName(isPlan ? 'plan.md' : 'train.py')
    setPasteContent(isPlan ? DEMO_PLAN : DEMO_EXECUTION)
    setError('')
  }

  return (
    <div className={`upload-area ${role}`}>
      <div className="upload-area-header">
        <span className={`role-tag ${role}`}>
          {isPlan ? '计划' : '执行'}
        </span>
        <span className="upload-area-title">
          {isPlan ? '实验计划' : '实际执行(代码/配置/结果)'}
        </span>
      </div>
      <p className="muted upload-area-desc">
        {isPlan
          ? '上传实验设计文档、研究方案等,说明你打算怎么做。'
          : '上传实际代码、配置文件、运行结果等,说明你实际怎么做的。'}
      </p>

      <div className="upload-actions">
        <button disabled={busy} onClick={() => fileRef.current?.click()}>
          上传文件
        </button>
        <button disabled={busy} onClick={() => setPasteMode(!pasteMode)}>
          {pasteMode ? '收起粘贴框' : '粘贴文本内容'}
        </button>
        <button disabled={busy} onClick={loadDemo} title="一键填入演示材料">
          加载示例材料
        </button>
        <input
          ref={fileRef}
          type="file"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) handleUpload(f)
            e.target.value = ''
          }}
        />
      </div>

      {pasteMode && (
        <div className="paste-box">
          <input
            value={pasteName}
            onChange={(e) => setPasteName(e.target.value)}
            placeholder={isPlan ? '文件名,如 plan.md' : '文件名,如 train.py'}
          />
          <textarea
            rows={6}
            value={pasteContent}
            onChange={(e) => setPasteContent(e.target.value)}
            placeholder={
              isPlan
                ? '粘贴实验计划、研究方案…'
                : '粘贴代码、配置或运行结果…'
            }
          />
          <button className="primary" disabled={busy} onClick={handlePaste}>
            提交文本材料
          </button>
        </div>
      )}

      {error && <div className="error">{error}</div>}

      {lastResult && (
        <div className="ingest-result">
          <h4>
            {lastResult.filename}({isPlan ? '计划' : '执行'})
          </h4>
          {lastResult.ocr_required && (
            <div className="warn">
              OCR 缺口:{lastResult.ocr_note || '该材料含未提取内容,需 OCR。'}
            </div>
          )}
          <div>提取到 {lastResult.extracted_facts.length} 条待确认事实</div>
          {lastResult.dropped.length > 0 && (
            <div className="warn">
              {lastResult.dropped.length} 条提取结果因引用校验失败被丢弃(防幻觉)
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** 第二步:收集材料。计划与执行分两个独立区域上传。
 * 材料列表下方自动显示缺口分析,每上传一份材料自动刷新。
 */
export function UploadPage({ sessionId, onNext, onBack }: Props) {
  const [materials, setMaterials] = useState<MaterialMeta[]>([])
  const [gaps, setGaps] = useState<GapAnalysis | null>(null)

  useEffect(() => {
    refresh()
  }, [])

  /** 材料变化时自动刷新缺口分析 */
  useEffect(() => {
    analyzeGaps(sessionId).then(setGaps).catch(() => {})
  }, [sessionId, materials.length])

  async function refresh() {
    try {
      setMaterials(await listMaterials(sessionId))
    } catch {
      /* 忽略 */
    }
  }

  const planMaterials = materials.filter((m) => m.role === 'plan')
  const execMaterials = materials.filter((m) => m.role === 'execution')

  const priorityColor: Record<string, string> = {
    high: '#d93025',
    medium: '#e37400',
    low: '#1a73e8',
  }
  const sufficiencyLabel: Record<string, string> = {
    sufficient: '材料充足',
    partial: '部分充足',
    insufficient: '材料不足',
    unknown: '未知',
  }

  return (
    <div className="page">
      <h2>第二步:收集材料</h2>
      <p className="muted">
        分别上传<strong>实验计划</strong>和<strong>实际执行</strong>材料——
        两者不一致本身就是重要线索。支持文本、代码、配置、结果文件;PDF 扫描件会标注 OCR 缺口。
      </p>

      <div className="upload-areas">
        <UploadArea sessionId={sessionId} role="plan" onUploaded={refresh} />
        <UploadArea sessionId={sessionId} role="execution" onUploaded={refresh} />
      </div>

      {materials.length > 0 && (
        <div className="material-list">
          <h4>已上传材料</h4>
          {planMaterials.length > 0 && (
            <div className="material-group">
              <div className="material-group-label">计划({planMaterials.length})</div>
              {planMaterials.map((m) => (
                <div key={m.material_id} className="material-item">
                  <span className="role-tag plan">计划</span>
                  <span>{m.filename}</span>
                  <span className="muted">{m.content_length} 字符</span>
                  {m.ocr_required && <span className="warn">需 OCR</span>}
                </div>
              ))}
            </div>
          )}
          {execMaterials.length > 0 && (
            <div className="material-group">
              <div className="material-group-label">执行({execMaterials.length})</div>
              {execMaterials.map((m) => (
                <div key={m.material_id} className="material-item">
                  <span className="role-tag execution">执行</span>
                  <span>{m.filename}</span>
                  <span className="muted">{m.content_length} 字符</span>
                  {m.ocr_required && <span className="warn">需 OCR</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 缺口分析:自动刷新,告诉用户还缺什么 */}
      {gaps && (
        <div className="gap-status">
          <div className="agent-section-header">
            <span>🤖 材料缺口分析</span>
            <span className={`agent-tag suf-${gaps.sufficiency}`}>
              {sufficiencyLabel[gaps.sufficiency] ?? gaps.sufficiency}
            </span>
          </div>
          {gaps.gaps.length === 0 ? (
            <div className="success">
              材料覆盖了已审查维度的基本要求,可以进入下一步确认事实。
            </div>
          ) : (
            <div className="agent-subsection">
              {gaps.gaps.map((g, i) => (
                <div key={i} className="agent-item gap-item">
                  <span
                    className="agent-severity"
                    style={{ color: priorityColor[g.priority] ?? '#5f6368' }}
                  >
                    [{g.priority}]
                  </span>
                  <strong>{g.missing}</strong>
                  <div className="muted">原因:{g.reason}</div>
                  <div className="muted">如何补充:{g.how_to_provide}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="page-actions">
        <button onClick={onBack}>上一步</button>
        <button className="primary" onClick={onNext}>
          下一步:确认提取的事实
        </button>
      </div>
    </div>
  )
}